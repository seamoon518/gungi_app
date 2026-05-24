"""
Phase 2: 座標降下法で評価関数の重みを最適化する（Texel Tuning）。

損失関数:
    E(pos) = 1 / (1 + 10^(-eval(pos,"white",weights) / K))
    Loss   = mean( (result - E(pos))^2 )
    result: 白勝=1.0, 引分=0.5, 黒勝=0.0

Usage:
    python -m scripts.texel_tune \\
        --positions data/tuning/positions.pkl \\
        --hours 2 --out logic/ai/weights/tier2.yaml
"""

import argparse
import copy
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

from logic.ai.evaluate import evaluate
from logic.ai.weights import load_weights
from scripts.generate_positions import deserialize_state

# ── 定数 ─────────────────────────────────────────────────────────────────────

SIGMOID_K = 600.0  # スケーリング係数（駒1枚差 ≈ 65% 勝率になるよう設定）

# チューニング対象パラメータ: (YAML パス, 1ステップ幅, 最小値, 最大値, 表示名)
TUNABLE_PARAMS = [
    # 駒価値
    ("piece_values.TAI", 25,   400, 1200, "大"),
    ("piece_values.CHU", 25,   400, 1000, "中"),
    ("piece_values.OZU", 25,   200,  900, "弩"),
    ("piece_values.TSU", 25,   200,  800, "筒"),
    ("piece_values.KIB", 25,   100,  700, "馬"),
    ("piece_values.YAR", 25,   100,  700, "槍"),
    ("piece_values.YUM", 25,   100,  700, "弓"),
    ("piece_values.SHO", 25,   100,  700, "小"),
    ("piece_values.SAM", 25,   100,  600, "侍"),
    ("piece_values.SHI", 25,    50,  600, "忍"),
    ("piece_values.BOU", 25,    50,  500, "謀"),
    ("piece_values.TOR", 25,    50,  500, "砦"),
    ("piece_values.HYO", 10,    30,  300, "兵"),
    # 手駒比率
    ("hand_piece_ratio.opening", 0.05, 1.0, 2.0, "手駒比率(序盤)"),
    ("hand_piece_ratio.middle",  0.05, 1.0, 2.0, "手駒比率(中盤)"),
    ("hand_piece_ratio.endgame", 0.05, 1.0, 2.5, "手駒比率(終盤)"),
    # 位置評価
    ("center_weight",  1, 0,  10, "中央重み"),
    ("forward_weight", 1, 0,  15, "前進重み"),
    # 帅安全
    ("sui_safety_penalty", 2, 5, 50, "帅安全ペナルティ"),
    # スタック
    ("stack_height_bonus.1", 0.02, 1.00, 1.60, "スタック2段ボーナス"),
    ("stack_height_bonus.2", 0.02, 1.00, 2.00, "スタック3段ボーナス"),
    # 機動力
    ("mobility_weight", 1, 0, 10, "機動力重み"),
    # 跳び駒
    ("jumping_threat_weight",     2,  0, 50,  "跳び駒脅威重み"),
    ("jumping_sui_threat_weight", 5, 10, 200, "跳び駒帅脅威重み"),
    # その他
    ("sui_fortress_weight",    1,    0,   30, "帅囲い重み"),
    ("isolated_penalty_ratio", 0.02, 0.0, 0.5, "孤立ペナルティ比率"),
    ("bou_defect_weight",      0.05, 0.0, 1.0, "謀動的価値重み"),
]


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-x / SIGMOID_K))


def _get(weights: dict, path: str):
    parts = path.split(".")
    v = weights
    for p in parts:
        v = v[int(p)] if isinstance(v, list) else v[p]
    return v


def _set(weights: dict, path: str, value) -> dict:
    w = copy.deepcopy(weights)
    parts = path.split(".")
    target = w
    for p in parts[:-1]:
        target = target[int(p)] if isinstance(target, list) else target[p]
    last = parts[-1]
    if isinstance(target, list):
        target[int(last)] = value
    else:
        target[last] = value
    return w


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── 損失計算 ──────────────────────────────────────────────────────────────────

def compute_loss(positions: list, weights: dict) -> float:
    """Texel MSE 損失を返す。"""
    total = 0.0
    for state, result in positions:
        score = evaluate(state, "white", weights)
        e = _sigmoid(score)
        total += (result - e) ** 2
    return total / len(positions)


# ── 座標降下 ──────────────────────────────────────────────────────────────────

def tune(
    positions_raw: list,
    weights: dict,
    time_budget_hours: float,
    out_path: str,
) -> dict:
    """
    座標降下法で weights を最適化して返す。
    引き分けポジション（result=0.5）は除外して決着局のみ使用する。
    チェックポイントを out_path に随時保存する。
    """
    deadline = time.time() + time_budget_hours * 3600

    # 引き分け除外: result=0.5 は score=0 最適解になり全重みが 0 に収束するため
    decisive = [(d, r) for d, r in positions_raw if r != 0.5]
    draws    = len(positions_raw) - len(decisive)
    print(f"[tune] positions: total={len(positions_raw)}  "
          f"decisive={len(decisive)}  draws_removed={draws}", flush=True)

    if len(decisive) < 100:
        print("[tune] WARNING: decisive positions too few (<100). "
              "Tuning may be unreliable.", flush=True)

    print(f"[tune] deserializing {len(decisive)} decisive positions ...", flush=True)
    t0 = time.time()
    positions = [(deserialize_state(d), r) for d, r in decisive]
    print(f"[tune] done  ({time.time()-t0:.1f}s)", flush=True)

    current_loss = compute_loss(positions, weights)
    print(f"[tune] initial loss = {current_loss:.6f}", flush=True)

    best = copy.deepcopy(weights)
    iteration = 0
    start = time.time()

    while time.time() < deadline:
        iteration += 1
        changes = []

        for path, delta, lo, hi, name in TUNABLE_PARAMS:
            if time.time() >= deadline:
                break

            cur_val = _get(best, path)

            # +delta
            vp = _clamp(cur_val + delta, lo, hi)
            lp = compute_loss(positions, _set(best, path, vp)) if vp != cur_val else 1e9

            # -delta
            vm = _clamp(cur_val - delta, lo, hi)
            lm = compute_loss(positions, _set(best, path, vm)) if vm != cur_val else 1e9

            best_new_loss = min(lp, lm)
            if best_new_loss < current_loss:
                if lp <= lm:
                    best = _set(best, path, vp)
                    new_val = vp
                else:
                    best = _set(best, path, vm)
                    new_val = vm
                current_loss = best_new_loss
                changes.append(f"{path}:{cur_val}->{new_val}")

        elapsed = time.time() - start
        remaining = max(0, deadline - time.time())
        msg = (
            f"  iter={iteration:3d}  loss={current_loss:.6f}"
            f"  Dparams={len(changes):2d}"
            f"  elapsed={elapsed/3600:.2f}h  remaining={remaining/3600:.2f}h"
        )
        print(msg, flush=True)
        if changes:
            # ASCII only to avoid cp932 encoding issues on Windows console
            safe = ', '.join(changes[:6]).encode('ascii', errors='replace').decode('ascii')
            print(f"    {safe}", flush=True)

        # チェックポイント保存
        _save_yaml(best, out_path)

        if not changes:
            print("[tune] 収束（このイテレーションで改善なし）", flush=True)
            break

    print(f"[tune] done  final_loss={current_loss:.6f}  iterations={iteration}",
          flush=True)
    return best


# ── YAML 保存 ─────────────────────────────────────────────────────────────────

def _save_yaml(weights: dict, path: str) -> None:
    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(weights, f, allow_unicode=True,
                  default_flow_style=False, sort_keys=False)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Texel Tuning")
    parser.add_argument("--positions", default="data/tuning/positions.pkl")
    parser.add_argument("--hours",     type=float, default=2.0)
    parser.add_argument("--out",       default="logic/ai/weights/tier2.yaml")
    args = parser.parse_args()

    with open(args.positions, "rb") as f:
        positions_raw = pickle.load(f)
    print(f"[tune] {len(positions_raw)} positions loaded from {args.positions}")

    weights = load_weights("tier1")
    optimized = tune(positions_raw, weights, args.hours, args.out)
    _save_yaml(optimized, args.out)
    print(f"[tune] saved → {args.out}")


if __name__ == "__main__":
    main()
