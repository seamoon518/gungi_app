"""
Texel Tuning overnight runner.

Phase 1 (4h): 自己対戦でポジションデータを生成
Phase 2 (2h): 座標降下法で重みを最適化
完了後 tier2.yaml と AI_TUNING_LOG.md を更新する。

Usage:
    cd backend
    python -m scripts.run_overnight
    python -m scripts.run_overnight --phase1-hours 4 --phase2-hours 2 --parallel 4
"""

import argparse
import copy
import datetime
import pathlib
import pickle
import sys
import time


def _fix_path():
    p = str(pathlib.Path(__file__).parent.parent.absolute())
    if p not in sys.path:
        sys.path.insert(0, p)


_fix_path()

POSITIONS_PATH = "data/tuning/positions.pkl"
TIER2_PATH     = "logic/ai/weights/tier2.yaml"
LOG_PATH       = str(pathlib.Path(__file__).parent.parent.parent / "AI_TUNING_LOG.md")


# ── ログ更新 ──────────────────────────────────────────────────────────────────

def _update_log(
    tier1_w: dict,
    tier2_w: dict,
    n_positions: int,
    total_hours: float,
    n_iterations: int,
    initial_loss: float,
    final_loss: float,
) -> None:
    today = datetime.date.today().isoformat()

    pv1 = tier1_w.get("piece_values", {})
    pv2 = tier2_w.get("piece_values", {})

    pieces = [
        ("TAI", "大"), ("CHU", "中"), ("OZU", "弩"), ("TSU", "筒"),
        ("KIB", "馬"), ("YAR", "槍"), ("YUM", "弓"), ("SHO", "小"),
        ("SAM", "侍"), ("SHI", "忍"), ("BOU", "謀"), ("TOR", "砦"),
        ("HYO", "兵"),
    ]

    # 駒価値テーブル
    pv_rows = ""
    for en, jp in pieces:
        v1 = pv1.get(en, "—")
        v2 = pv2.get(en, "—")
        diff = (v2 - v1) if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) else "—"
        sign = "+" if isinstance(diff, (int, float)) and diff > 0 else ""
        pv_rows += f"| {jp}({en}) | {v1} | {v2} | {sign}{diff} |\n"

    hr1 = tier1_w.get("hand_piece_ratio", {})
    hr2 = tier2_w.get("hand_piece_ratio", {})

    # その他パラメータ比較
    other_keys = [
        ("center_weight",            "中央重み"),
        ("forward_weight",           "前進重み"),
        ("sui_safety_penalty",       "帅安全ペナルティ"),
        ("mobility_weight",          "機動力重み"),
        ("jumping_threat_weight",    "跳び駒脅威重み"),
        ("jumping_sui_threat_weight","跳び駒帅脅威重み"),
        ("sui_fortress_weight",      "帅囲い重み"),
        ("isolated_penalty_ratio",   "孤立ペナルティ比率"),
        ("bou_defect_weight",        "謀動的価値重み"),
    ]
    other_rows = ""
    for key, label in other_keys:
        v1 = tier1_w.get(key, "—")
        v2 = tier2_w.get(key, "—")
        other_rows += f"| {label} | {v1} | {v2} |\n"

    # stack_height_bonus
    shb1 = tier1_w.get("stack_height_bonus", ["—", "—", "—"])
    shb2 = tier2_w.get("stack_height_bonus", ["—", "—", "—"])

    section = f"""
---

## Tier 2（Texel Tuning後）  {today}

### 駒価値の変化
| 駒 | Tier 1 | Tier 2 | 変化 |
|---|---|---|---|
{pv_rows}
### 手駒比率の変化
| フェーズ | Tier 1 | Tier 2 |
|---|---|---|
| 序盤 | {hr1.get('opening', '—')} | {hr2.get('opening', '—')} |
| 中盤 | {hr1.get('middle',  '—')} | {hr2.get('middle',  '—')} |
| 終盤 | {hr1.get('endgame', '—')} | {hr2.get('endgame', '—')} |

### スタック高ボーナスの変化
| 高さ | Tier 1 | Tier 2 |
|---|---|---|
| 2段 | {shb1[1] if len(shb1) > 1 else '—'} | {shb2[1] if len(shb2) > 1 else '—'} |
| 3段 | {shb1[2] if len(shb1) > 2 else '—'} | {shb2[2] if len(shb2) > 2 else '—'} |

### その他パラメータの変化
| パラメータ | Tier 1 | Tier 2 |
|---|---|---|
{other_rows}
### 実行情報
| 項目 | 値 |
|---|---|
| 使用ポジション数 | {n_positions:,} |
| 座標降下イテレーション数 | {n_iterations} |
| 初期 Texel 損失 | {initial_loss:.6f} |
| 最終 Texel 損失 | {final_loss:.6f} |
| 損失改善率 | {(1 - final_loss/initial_loss)*100:.1f}% |
| 総実行時間 | {total_hours:.2f}h |

### パフォーマンス（チューニング後）
*ベンチマーク実行後に更新*
"""

    existing = pathlib.Path(LOG_PATH).read_text(encoding="utf-8") if pathlib.Path(LOG_PATH).exists() else ""
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write(existing + section)

    print(f"[log] AI_TUNING_LOG.md updated → {LOG_PATH}", flush=True)


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Texel Tuning overnight runner")
    parser.add_argument("--phase1-hours", type=float, default=4.0, dest="p1_hours")
    parser.add_argument("--phase2-hours", type=float, default=2.0, dest="p2_hours")
    parser.add_argument("--parallel",     type=int,   default=4)
    parser.add_argument("--level",        default="joukyuu")
    parser.add_argument("--tl",           type=float, default=1.0, dest="time_limit")
    args = parser.parse_args()

    total_start = time.time()
    print("=" * 60)
    print("  Texel Tuning Overnight Run")
    print(f"  Phase 1: {args.p1_hours}h  Phase 2: {args.p2_hours}h")
    print(f"  Level: {args.level}  Parallel: {args.parallel}  TL: {args.time_limit}s/move")
    print(f"  Start: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60, flush=True)

    # ── Phase 1 ──────────────────────────────────────────────────────────────
    print(f"\n=== Phase 1: Position Generation ({args.p1_hours}h) ===", flush=True)
    from scripts.generate_positions import generate
    p1_start = time.time()
    n_positions = generate(
        out_path=POSITIONS_PATH,
        level=args.level,
        time_budget_hours=args.p1_hours,
        parallel=args.parallel,
        move_time_limit=args.time_limit,
    )
    p1_elapsed = time.time() - p1_start
    print(f"Phase 1 done: {n_positions:,} positions  {p1_elapsed/3600:.2f}h\n", flush=True)

    # ── Phase 2 ──────────────────────────────────────────────────────────────
    print(f"=== Phase 2: Texel Tuning ({args.p2_hours}h) ===", flush=True)
    from scripts.texel_tune import tune, _save_yaml, compute_loss, deserialize_state
    from logic.ai.weights import load_weights

    with open(POSITIONS_PATH, "rb") as f:
        positions_raw = pickle.load(f)

    tier1_weights = load_weights("tier1")
    tier2_initial = copy.deepcopy(tier1_weights)

    # 初期損失（ログ用）
    print("[tune] 初期損失を計算中...", flush=True)
    positions_cached = [(deserialize_state(d), r) for d, r in positions_raw]
    initial_loss = compute_loss(positions_cached, tier1_weights)
    print(f"[tune] initial loss: {initial_loss:.6f}", flush=True)

    p2_start = time.time()
    optimized = tune(positions_raw, tier1_weights, args.p2_hours, TIER2_PATH)
    _save_yaml(optimized, TIER2_PATH)
    p2_elapsed = time.time() - p2_start

    # 最終損失（決着局のみで再計算）
    decisive_cached = [(s, r) for s, r in positions_cached if r != 0.5]
    final_loss = compute_loss(decisive_cached, optimized) if decisive_cached else float('nan')

    n_iter_approx = max(1, int(p2_elapsed / 45))  # 決着局のみで ~45秒/iter

    total_elapsed = time.time() - total_start
    print(f"\nPhase 2 done: {p2_elapsed/3600:.2f}h", flush=True)
    print(f"Total elapsed: {total_elapsed/3600:.2f}h", flush=True)
    print(f"Loss: {initial_loss:.6f} -> {final_loss:.6f}"
          f"  improvement: {(1-final_loss/initial_loss)*100:.1f}%", flush=True)
    print(f"tier2.yaml saved -> {TIER2_PATH}", flush=True)

    # ── ログ更新 ──────────────────────────────────────────────────────────────
    _update_log(
        tier1_w=tier2_initial,
        tier2_w=optimized,
        n_positions=n_positions,
        total_hours=total_elapsed / 3600,
        n_iterations=n_iter_approx,
        initial_loss=initial_loss,
        final_loss=final_loss,
    )

    print("\n=== ALL DONE ===", flush=True)
    print(f"  完了: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"  出力: {TIER2_PATH}", flush=True)
    print(f"  ログ: {LOG_PATH}", flush=True)


if __name__ == "__main__":
    main()
