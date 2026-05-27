"""
蒸留ベースの重みチューニング。

損失関数: MSE(static_eval(pos, weights), pvs_score_target)
  = 静的評価関数を、より深い探索のスコアに近づける

ゲーム結果を使わないため引き分け問題が完全に解消される。

Usage:
    python -m scripts.texel_tune_distill \\
        --positions data/tuning/distill_positions.pkl \\
        --hours 4 --out logic/ai/weights/tier2.yaml
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

# チューニング対象パラメータ: (path, delta, min_val, max_val, 説明)
TUNABLE_PARAMS = [
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
    ("hand_piece_ratio.opening", 0.05, 1.0, 2.0, "手駒比率(序盤)"),
    ("hand_piece_ratio.middle",  0.05, 1.0, 2.0, "手駒比率(中盤)"),
    ("hand_piece_ratio.endgame", 0.05, 1.0, 2.5, "手駒比率(終盤)"),
    ("center_weight",  1, 0,  15, "中央重み"),
    ("forward_weight", 1, 0,  15, "前進重み"),
    ("sui_safety_penalty", 2, 5, 50, "帅安全ペナルティ"),
    ("stack_height_bonus.1", 0.02, 1.00, 1.60, "スタック2段"),
    ("stack_height_bonus.2", 0.02, 1.00, 2.00, "スタック3段"),
    ("mobility_weight",          1, 0,  10, "機動力重み"),
    ("jumping_threat_weight",    2, 0,  50, "跳び駒脅威重み"),
    ("jumping_sui_threat_weight",5, 10, 200, "跳び駒帅脅威重み"),
    ("sui_fortress_weight",      1, 0,  30, "帅囲い重み"),
    ("isolated_penalty_ratio",   0.02, 0.0, 0.5, "孤立ペナルティ比率"),
    ("bou_defect_weight",        0.05, 0.0, 1.0, "謀動的価値重み"),
    ("hanging_penalty_ratio",    0.02, 0.0, 0.5, "ぶら下がりペナルティ"),
    ("frontline_weight",         1,    0,  20, "前線重み"),
    ("sui_mobility_weight",      1,    0,  15, "帅逃げ場重み"),
    ("ray_blocking_weight",      1,    0,  15, "射線遮断重み"),
]


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


def compute_loss(positions: list, weights: dict) -> float:
    """
    MSE(static_eval, pvs_target) を返す。
    ゲーム結果は使用しない。
    """
    total = 0.0
    for state, pvs_target in positions:
        static_score = evaluate(state, "white", weights)
        total += (pvs_target - static_score) ** 2
    return total / len(positions)


def tune(
    positions_raw: list,
    weights: dict,
    time_budget_hours: float,
    out_path: str,
) -> dict:
    deadline = time.time() + time_budget_hours * 3600
    start = time.time()

    print(f"[distill-tune] {len(positions_raw)} 件を deserialize 中...", flush=True)
    t0 = time.time()
    positions = [(deserialize_state(d), s) for d, s in positions_raw]
    print(f"[distill-tune] done ({time.time()-t0:.1f}s)", flush=True)

    # スコア分布を表示
    scores = [s for _, s in positions]
    print(f"[distill-tune] target score stats: "
          f"min={min(scores):.0f}  max={max(scores):.0f}  "
          f"mean={sum(scores)/len(scores):.0f}", flush=True)

    current_loss = compute_loss(positions, weights)
    print(f"[distill-tune] 初期損失 = {current_loss:.2f}", flush=True)

    best = copy.deepcopy(weights)
    iteration = 0

    while time.time() < deadline:
        iteration += 1
        changes = []

        for path, delta, lo, hi, name in TUNABLE_PARAMS:
            if time.time() >= deadline:
                break

            cur_val = _get(best, path)

            vp = _clamp(cur_val + delta, lo, hi)
            lp = compute_loss(positions, _set(best, path, vp)) if vp != cur_val else 1e18

            vm = _clamp(cur_val - delta, lo, hi)
            lm = compute_loss(positions, _set(best, path, vm)) if vm != cur_val else 1e18

            if min(lp, lm) < current_loss:
                if lp <= lm:
                    best = _set(best, path, vp)
                    new_val = vp
                else:
                    best = _set(best, path, vm)
                    new_val = vm
                current_loss = min(lp, lm)
                changes.append(f"{path}:{cur_val}->{new_val}")

        elapsed = time.time() - start
        remaining = max(0, deadline - time.time())
        print(
            f"  iter={iteration:3d}  loss={current_loss:.2f}"
            f"  Dparams={len(changes):2d}"
            f"  elapsed={elapsed/3600:.2f}h  remaining={remaining/3600:.2f}h",
            flush=True,
        )
        if changes:
            safe = ", ".join(changes[:5]).encode("ascii", errors="replace").decode("ascii")
            print(f"    {safe}", flush=True)

        _save_yaml(best, out_path)

        if not changes:
            print("[distill-tune] 収束", flush=True)
            break

    print(f"[distill-tune] 完了  final_loss={current_loss:.2f}  iterations={iteration}",
          flush=True)
    return best


def _save_yaml(weights: dict, path: str) -> None:
    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(weights, f, allow_unicode=True,
                  default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", default="data/tuning/distill_positions.pkl")
    parser.add_argument("--hours",     type=float, default=4.0)
    parser.add_argument("--out",       default="logic/ai/weights/tier2.yaml")
    parser.add_argument("--base",      default="tier1", help="起点となる weights 名")
    args = parser.parse_args()

    with open(args.positions, "rb") as f:
        positions_raw = pickle.load(f)
    print(f"[distill-tune] {len(positions_raw)} 件ロード ({args.positions})")

    weights = load_weights(args.base)
    optimized = tune(positions_raw, weights, args.hours, args.out)
    _save_yaml(optimized, args.out)
    print(f"[distill-tune] saved -> {args.out}")


if __name__ == "__main__":
    main()
