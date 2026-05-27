"""
蒸留ベース 20 時間 overnight runner。

スケジュール（合計 ~20h）:
  Phase 1 ( 8h): 蒸留データ生成（pvs スコア付き局面）
  Phase 2 ( 4h): Round 1 チューニング
  Phase 3 ( 1h): tier1 vs tier2 ベンチマーク（20 局）
  Phase 4 ( 5h): Round 2 チューニング（tier2 起点）
  Phase 5 ( 1h): 最終ベンチマーク + ログ更新
  余裕   ( 1h): バッファ

Usage:
    cd backend
    python -m scripts.run_distillation
    python -m scripts.run_distillation --p1 8 --p2 4 --p4 5 --parallel 4
"""

import argparse
import copy
import datetime
import pathlib
import pickle
import sys
import time

import yaml


def _fix_path():
    p = str(pathlib.Path(__file__).parent.parent.absolute())
    if p not in sys.path:
        sys.path.insert(0, p)


_fix_path()

DISTILL_PATH = "data/tuning/distill_positions.pkl"
TIER2_PATH   = "logic/ai/weights/tier2.yaml"
LOG_PATH     = str(pathlib.Path(__file__).parent.parent.parent / "AI_TUNING_LOG.md")


def _save_yaml(weights: dict, path: str) -> None:
    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(weights, f, allow_unicode=True,
                  default_flow_style=False, sort_keys=False)


def _update_log(tier1_w, tier2_w, n_positions, bench1, bench2, total_hours):
    today = datetime.date.today().isoformat()

    pv1 = tier1_w.get("piece_values", {})
    pv2 = tier2_w.get("piece_values", {})

    pieces = [
        ("TAI","大"),("CHU","中"),("OZU","弩"),("TSU","筒"),
        ("KIB","馬"),("YAR","槍"),("YUM","弓"),("SHO","小"),
        ("SAM","侍"),("SHI","忍"),("BOU","謀"),("TOR","砦"),("HYO","兵"),
    ]
    pv_rows = ""
    for en, jp in pieces:
        v1 = pv1.get(en, "-")
        v2 = pv2.get(en, "-")
        diff = (v2 - v1) if isinstance(v1,(int,float)) and isinstance(v2,(int,float)) else "-"
        sign = "+" if isinstance(diff,(int,float)) and diff > 0 else ""
        pv_rows += f"| {jp}({en}) | {v1} | {v2} | {sign}{diff} |\n"

    bench1_str = f"{bench1['wins']}W {bench1['draws']}D {bench1['losses']}L" if bench1 else "未実施"
    bench2_str = f"{bench2['wins']}W {bench2['draws']}D {bench2['losses']}L" if bench2 else "未実施"

    section = f"""
---

## 蒸留チューニング ({today})

### 手法
ゲーム結果でなく **pvs スコア（探索評価値）を教師信号** として使用。
引き分け問題を根本解決。損失 = MSE(static_eval, pvs_score)。

### 駒価値の変化
| 駒 | Tier 1 | Tier 2 | 変化 |
|---|---|---|---|
{pv_rows}
### 実行情報
| 項目 | 値 |
|---|---|
| 学習ポジション数 | {n_positions:,} |
| 総実行時間 | {total_hours:.2f}h |

### パフォーマンス
| 対戦 | 結果（tier1 視点） |
|---|---|
| Round 1 後 (20局) | {bench1_str} |
| Round 2 後 (20局) | {bench2_str} |
"""

    p = pathlib.Path(LOG_PATH)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    with open(p, "w", encoding="utf-8") as f:
        f.write(existing + section)
    print(f"[log] AI_TUNING_LOG.md updated", flush=True)


def _run_benchmark(n_games: int = 20) -> dict:
    """tier1 vs tier2 の簡易ベンチマーク。"""
    from scripts.benchmark import run_benchmark
    result = run_benchmark(
        baseline="tier1",
        candidate="tier2",
        games=n_games,
        level="joukyuu",
        parallel=2,
        time_budget=1.0,
        output_dir="data/benchmarks/",
        save_games=False,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="蒸留 overnight runner")
    parser.add_argument("--p1",       type=float, default=8.0,  help="Phase1 時間（データ生成）")
    parser.add_argument("--p2",       type=float, default=4.0,  help="Phase2 時間（Round1 チューニング）")
    parser.add_argument("--p3",       type=float, default=1.0,  help="Phase3 時間（ベンチマーク）")
    parser.add_argument("--p4",       type=float, default=5.0,  help="Phase4 時間（Round2 チューニング）")
    parser.add_argument("--parallel", type=int,   default=4)
    parser.add_argument("--level",    default="joukyuu")
    parser.add_argument("--tl",       type=float, default=1.0,  dest="time_limit")
    parser.add_argument("--skip-gen", action="store_true",
                        help="Phase1 をスキップして既存の pkl を再利用")
    parser.add_argument("--base",     default="tier1",
                        help="Round1 の起点となる weights 名（例: tier2）")
    args = parser.parse_args()

    total_start = time.time()
    print("=" * 60, flush=True)
    print("  蒸留ベース AI チューニング overnight runner", flush=True)
    skip_gen = getattr(args, "skip_gen", False)
    print(f"  P1={'skip' if skip_gen else args.p1}h  P2={args.p2}h  P3={args.p3}h  P4={args.p4}h", flush=True)
    print(f"  Level={args.level}  Parallel={args.parallel}  TL={args.time_limit}s/手", flush=True)
    print(f"  開始: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 60, flush=True)

    # ── Phase 1: データ生成 ────────────────────────────────────────────────────
    if skip_gen:
        import pathlib, pickle as _pkl
        if not pathlib.Path(DISTILL_PATH).exists():
            raise FileNotFoundError(f"--skip-gen 指定だが {DISTILL_PATH} が存在しない")
        with open(DISTILL_PATH, "rb") as f:
            _tmp = _pkl.load(f)
        n_positions = len(_tmp)
        del _tmp
        print(f"\n=== Phase 1: スキップ（既存データ再利用: {n_positions:,} ポジション）===\n",
              flush=True)
    else:
        print(f"\n=== Phase 1: 蒸留データ生成 ({args.p1}h) ===", flush=True)
        from scripts.generate_positions_distill import generate
        n_positions = generate(
            out_path=DISTILL_PATH,
            level=args.level,
            time_budget_hours=args.p1,
            parallel=args.parallel,
            move_time_limit=args.time_limit,
        )
        print(f"Phase 1 完了: {n_positions:,} ポジション\n", flush=True)

    # ── Phase 2: Round 1 チューニング ──────────────────────────────────────────
    print(f"=== Phase 2: Round 1 チューニング ({args.p2}h, base={args.base}) ===", flush=True)
    from scripts.texel_tune_distill import tune, compute_loss, deserialize_state
    from logic.ai.weights import load_weights

    with open(DISTILL_PATH, "rb") as f:
        positions_raw = pickle.load(f)

    tier1_weights = load_weights("tier1")
    base_weights  = load_weights(args.base)
    tier2_r1 = tune(positions_raw, base_weights, args.p2, TIER2_PATH)
    _save_yaml(tier2_r1, TIER2_PATH)
    print(f"Phase 2 完了\n", flush=True)

    # ── Phase 3: ベンチマーク Round 1 ─────────────────────────────────────────
    print(f"=== Phase 3: ベンチマーク Round 1 ===", flush=True)
    bench1 = None
    try:
        bench1 = _run_benchmark(n_games=20)
        print(f"Phase 3 結果: {bench1['wins']}W {bench1['draws']}D {bench1['losses']}L"
              f"  win_rate={bench1['win_rate']:.1%}\n", flush=True)
    except Exception as e:
        print(f"Phase 3 失敗: {e}\n", flush=True)

    # ── Phase 4: Round 2 チューニング ──────────────────────────────────────────
    # tier1 が大幅優位（tier1勝利 > tier2勝利×2）→ tier1 起点でやり直し
    # それ以外（tier2 優位 or 互角）→ tier2 起点で続行
    base_for_r2 = tier2_r1
    if bench1 and bench1["wins"] > bench1["losses"] * 2:
        print("[!] Round 1 の tier2 が大幅に劣位 → tier1 起点でやり直し", flush=True)
        base_for_r2 = tier1_weights

    print(f"=== Phase 4: Round 2 チューニング ({args.p4}h) ===", flush=True)
    tier2_r2 = tune(positions_raw, base_for_r2, args.p4, TIER2_PATH)
    _save_yaml(tier2_r2, TIER2_PATH)
    print(f"Phase 4 完了\n", flush=True)

    # ── Phase 5: 最終ベンチマーク ──────────────────────────────────────────────
    print("=== Phase 5: 最終ベンチマーク ===", flush=True)
    bench2 = None
    try:
        bench2 = _run_benchmark(n_games=20)
        print(f"Phase 5 結果: {bench2['wins']}W {bench2['draws']}D {bench2['losses']}L"
              f"  win_rate={bench2['win_rate']:.1%}\n", flush=True)
    except Exception as e:
        print(f"Phase 5 失敗: {e}\n", flush=True)

    # ── ログ更新 ───────────────────────────────────────────────────────────────
    total_elapsed = time.time() - total_start
    _update_log(
        tier1_w=tier1_weights,
        tier2_w=tier2_r2,
        n_positions=n_positions,
        bench1=bench1,
        bench2=bench2,
        total_hours=total_elapsed / 3600,
    )

    print("\n=== ALL DONE ===", flush=True)
    print(f"  完了: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"  総実行時間: {total_elapsed/3600:.2f}h", flush=True)
    print(f"  出力: {TIER2_PATH}", flush=True)
    print(f"  ログ: {LOG_PATH}", flush=True)


if __name__ == "__main__":
    main()
