"""
反復蒸留ループ runner。

サイクルを繰り返す:
  1. データ生成  (gen_hours) — その時点の最強重みで自己対戦
  2. チューニング (tune_hours)
  3. ミニベンチ   (bench_games 局)
  4. tier2 が勝ち越し → 重みを採用して次サイクルへ
     tier1 大幅優位   → tier1 起点でやり直し

Usage:
    cd backend
    python -m scripts.run_iterative
    python -m scripts.run_iterative --cycles 5 --gen 3 --tune 1.5 --bench 6 --tl 5.0 --parallel 4
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

DISTILL_PATH   = "data/tuning/distill_positions.pkl"
TIER2_PATH     = "logic/ai/weights/tier2.yaml"
HISTORY_DIR    = pathlib.Path("logic/ai/weights/history")
LOG_PATH       = str(pathlib.Path(__file__).parent.parent.parent / "AI_TUNING_LOG.md")


def _save_yaml(weights: dict, path: str) -> None:
    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(weights, f, allow_unicode=True,
                  default_flow_style=False, sort_keys=False)


def _save_checkpoint(weights: dict, cycle: int, bench: dict | None, adopted: bool) -> str:
    """サイクルごとの重みをチェックポイントとして保存する。"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    win_rate = f"{bench['win_rate']:.0%}" if bench else "nobenч"
    status = "adopted" if adopted else "rejected"
    filename = f"iter_cycle{cycle:02d}_{date_str}_{win_rate}_{status}.yaml"
    path = HISTORY_DIR / filename

    # メタ情報をコメントとして先頭に付加
    bench_str = (f"{bench['wins']}W {bench['draws']}D {bench['losses']}L "
                 f"win_rate={bench['win_rate']:.1%}") if bench else "未実施"
    meta = (
        f"# cycle: {cycle}\n"
        f"# date: {datetime.datetime.now().isoformat()}\n"
        f"# bench (vs tier1): {bench_str}\n"
        f"# adopted: {adopted}\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(meta)
        yaml.dump(weights, f, allow_unicode=True,
                  default_flow_style=False, sort_keys=False)
    print(f"[checkpoint] 保存: {path}", flush=True)
    return str(path)


def _run_benchmark(n_games: int, parallel: int) -> dict:
    from scripts.benchmark import run_benchmark
    return run_benchmark(
        baseline="tier1",
        candidate="tier2",
        games=n_games,
        level="joukyuu",
        parallel=parallel,
        time_budget=1.0,
        output_dir="data/benchmarks/",
        save_games=False,
    )


def _update_log(cycle: int, tier1_w: dict, tier2_w: dict,
                n_new: int, bench: dict, elapsed_h: float) -> None:
    today = datetime.date.today().isoformat()
    pv1 = tier1_w.get("piece_values", {})
    pv2 = tier2_w.get("piece_values", {})
    pieces = [
        ("TAI","大"),("CHU","中"),("OZU","弩"),("TSU","筒"),
        ("KIB","馬"),("YAR","槍"),("YUM","弓"),("SHO","小"),
        ("SAM","侍"),("SHI","忍"),("BOU","謀"),("TOR","砦"),("HYO","兵"),
    ]
    rows = ""
    for en, jp in pieces:
        v1 = pv1.get(en, "-")
        v2 = pv2.get(en, "-")
        diff = (v2 - v1) if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) else "-"
        sign = "+" if isinstance(diff, (int, float)) and diff > 0 else ""
        rows += f"| {jp}({en}) | {v1} | {v2} | {sign}{diff} |\n"

    bench_str = (f"{bench['wins']}W {bench['draws']}D {bench['losses']}L "
                 f"win_rate={bench['win_rate']:.1%}") if bench else "未実施"

    adopted = bench and bench["wins"] >= bench["losses"]

    section = f"""
---

## 反復蒸留 サイクル {cycle} ({today})

### 駒価値の変化
| 駒 | Tier 1 | Tier 2 | 変化 |
|---|---|---|---|
{rows}
### 実行情報
| 項目 | 値 |
|---|---|
| 新規ポジション数 | {n_new:,} |
| サイクル実行時間 | {elapsed_h:.2f}h |
| ベンチ結果（tier1視点） | {bench_str} |
| tier2 採用 | {'YES' if adopted else 'NO（tier1起点に戻す）'} |
"""
    p = pathlib.Path(LOG_PATH)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    with open(p, "w", encoding="utf-8") as f:
        f.write(existing + section)
    print(f"[log] AI_TUNING_LOG.md updated (cycle {cycle})", flush=True)


def main():
    parser = argparse.ArgumentParser(description="反復蒸留ループ runner")
    parser.add_argument("--cycles",   type=int,   default=5,    help="サイクル数")
    parser.add_argument("--gen",      type=float, default=3.0,  help="1サイクルのデータ生成時間(h)")
    parser.add_argument("--tune",     type=float, default=1.5,  help="1サイクルのチューニング時間(h)")
    parser.add_argument("--bench",    type=int,   default=6,    help="1サイクルのベンチ局数")
    parser.add_argument("--tl",       type=float, default=5.0,  help="生成時の思考時間(s/手)")
    parser.add_argument("--parallel", type=int,   default=4)
    parser.add_argument("--level",    default="joukyuu")
    parser.add_argument("--tuner",    default="spsa",
                        choices=["spsa", "coord"], help="チューナー種別")
    parser.add_argument("--start-cycle", type=int, default=1,  help="途中再開用サイクル番号")
    args = parser.parse_args()

    total_start = time.time()
    print("=" * 60, flush=True)
    print("  反復蒸留ループ runner", flush=True)
    print(f"  cycles={args.cycles}  gen={args.gen}h  tune={args.tune}h  bench={args.bench}局", flush=True)
    print(f"  tl={args.tl}s/手  parallel={args.parallel}", flush=True)
    print(f"  開始: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"  予想総時間: {args.cycles * (args.gen + args.tune + 0.5):.1f}h", flush=True)
    print("=" * 60, flush=True)

    from scripts.generate_positions_distill import generate
    from scripts.texel_tune_distill import tune, tune_spsa
    from logic.ai.weights import load_weights

    _tuner = tune_spsa if args.tuner == "spsa" else tune
    print(f"[init] チューナー: {args.tuner}", flush=True)

    tier1_weights = load_weights("tier1")

    # 既存データがあれば引き継ぐ
    all_positions = []
    if pathlib.Path(DISTILL_PATH).exists():
        with open(DISTILL_PATH, "rb") as f:
            all_positions = pickle.load(f)
        print(f"[init] 既存データ引き継ぎ: {len(all_positions):,} ポジション", flush=True)

    # 現在の tier2 を起点にする（なければ tier1）
    try:
        best_weights = load_weights("tier2")
        print("[init] 起点: tier2", flush=True)
    except Exception:
        best_weights = copy.deepcopy(tier1_weights)
        print("[init] 起点: tier1", flush=True)

    for cycle in range(args.start_cycle, args.cycles + 1):
        cycle_start = time.time()
        print(f"\n{'='*60}", flush=True)
        print(f"  サイクル {cycle}/{args.cycles}  開始: {datetime.datetime.now().strftime('%H:%M:%S')}", flush=True)
        print(f"{'='*60}", flush=True)

        # ── データ生成（最強重みで自己対戦）─────────────────────────
        # 現在の best_weights を tier2 として一時保存し、生成スクリプトが参照できるようにする
        _save_yaml(best_weights, TIER2_PATH)
        print(f"\n[cycle {cycle}] Phase A: データ生成 ({args.gen}h, tl={args.tl}s)", flush=True)
        n_new = generate(
            out_path=DISTILL_PATH + f".cycle{cycle}.tmp",
            level=args.level,
            time_budget_hours=args.gen,
            parallel=args.parallel,
            move_time_limit=args.tl,
        )

        # 新データを累積
        with open(DISTILL_PATH + f".cycle{cycle}.tmp", "rb") as f:
            new_positions = pickle.load(f)
        all_positions.extend(new_positions)
        # 全累積データを保存
        with open(DISTILL_PATH, "wb") as f:
            pickle.dump(all_positions, f)
        print(f"[cycle {cycle}] 累積データ: {len(all_positions):,} ポジション (+{n_new:,})", flush=True)

        # ── チューニング ──────────────────────────────────────────────
        print(f"\n[cycle {cycle}] Phase B: チューニング ({args.tune}h)", flush=True)
        with open(DISTILL_PATH, "rb") as f:
            positions_raw = pickle.load(f)
        new_weights = _tuner(positions_raw, best_weights, args.tune, TIER2_PATH)
        _save_yaml(new_weights, TIER2_PATH)

        # ── ベンチマーク ──────────────────────────────────────────────
        print(f"\n[cycle {cycle}] Phase C: ベンチマーク ({args.bench}局)", flush=True)
        bench = None
        try:
            bench = _run_benchmark(args.bench, min(args.parallel, args.bench // 2))
            print(f"[cycle {cycle}] bench: {bench['wins']}W {bench['draws']}D {bench['losses']}L "
                  f"win_rate={bench['win_rate']:.1%}", flush=True)
        except Exception as e:
            print(f"[cycle {cycle}] ベンチ失敗: {e}", flush=True)

        # ── 採用判断 ──────────────────────────────────────────────────
        elapsed_h = (time.time() - cycle_start) / 3600
        adopted = not (bench and bench["wins"] > bench["losses"] * 2)
        if not adopted:
            print(f"[cycle {cycle}] tier1 大幅優位 → 次サイクルは tier1 起点でやり直し", flush=True)
            best_weights = copy.deepcopy(tier1_weights)
        else:
            best_weights = new_weights
            print(f"[cycle {cycle}] tier2 採用 → 次サイクルへ引き継ぎ", flush=True)

        _save_checkpoint(new_weights, cycle, bench, adopted)
        _update_log(cycle, tier1_weights, new_weights, n_new, bench, elapsed_h)

    total_elapsed = (time.time() - total_start) / 3600
    print(f"\n{'='*60}", flush=True)
    print(f"  全サイクル完了", flush=True)
    print(f"  総実行時間: {total_elapsed:.2f}h", flush=True)
    print(f"  完了: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
