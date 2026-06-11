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
import math
import pathlib
import pickle
import random
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
    ("arata_control_weight",     1,    0,  20, "新置きゾーン支配"),
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


def tune_spsa(
    positions_raw: list,
    weights: dict,
    time_budget_hours: float,
    out_path: str,
    batch_size: int = 5000,
) -> dict:
    """
    SPSA (Simultaneous Perturbation Stochastic Approximation) チューナー。
    全パラメータを同時にランダム方向へ摂動し勾配を推定する。
    座標降下が詰まる局所最適を抜け出せる。
    """
    deadline = time.time() + time_budget_hours * 3600
    start    = time.time()
    n        = len(TUNABLE_PARAMS)

    print(f"[spsa] {len(positions_raw)} 件を deserialize 中...", flush=True)
    t0 = time.time()
    positions = [(deserialize_state(d), s) for d, s in positions_raw]
    print(f"[spsa] done ({time.time()-t0:.1f}s)  batch_size={batch_size}", flush=True)

    # パラメータを [0, 1] に正規化
    def _to_norm(w: dict) -> list:
        return [(_get(w, p) - lo) / (hi - lo + 1e-9)
                for p, _, lo, hi, _ in TUNABLE_PARAMS]

    def _from_norm(theta: list) -> dict:
        w = copy.deepcopy(weights)
        for i, (path, step, lo, hi, _) in enumerate(TUNABLE_PARAMS):
            raw = theta[i] * (hi - lo) + lo
            # 整数ステップ: step>=1 なら丸める
            if step >= 1:
                raw = float(int(round(raw / step)) * int(step))
            else:
                raw = round(raw / step) * step
            w = _set(w, path, _clamp(raw, lo, hi))
        return w

    theta_init = _to_norm(weights)

    # 損失スケールを事前計算（損失が数百万オーダーになるため正規化して学習率崩壊を防ぐ）
    _scale_batch = random.sample(positions, min(batch_size, len(positions)))
    _init_w = _from_norm(theta_init)
    loss_scale = max(1.0, sum((t - evaluate(s, "white", _init_w)) ** 2
                              for s, t in _scale_batch) / len(_scale_batch))
    print(f"[spsa] loss_scale={loss_scale:.0f}", flush=True)

    def _batch_loss(theta: list) -> float:
        w = _from_norm(theta)
        batch = random.sample(positions, min(batch_size, len(positions)))
        return sum((t - evaluate(s, "white", w)) ** 2 for s, t in batch) / len(batch) / loss_scale

    # SPSA ハイパーパラメータ
    alpha = 0.602
    gamma = 0.101
    A = 100

    # 自動学習率調整: k=1時の a_k が ~0.05 になるよう設定（正規化損失スケール用）
    # avg_g は n パラメータの平均勾配なので、実際の g_hat_i はより大きい → 上限を 2.0 に絞る
    print("[spsa] 学習率を自動調整中...", flush=True)
    trial_delta = [random.choice([-1, 1]) for _ in range(n)]
    c_trial = 0.1
    tp = [_clamp(theta_init[i] + c_trial * trial_delta[i], 0.0, 1.0) for i in range(n)]
    tm = [_clamp(theta_init[i] - c_trial * trial_delta[i], 0.0, 1.0) for i in range(n)]
    Lp_trial = _batch_loss(tp)
    Lm_trial = _batch_loss(tm)
    avg_g = abs(Lp_trial - Lm_trial) / (2.0 * c_trial * n + 1e-9)
    target_step = 0.05
    a = max(1e-4, min(target_step * (A + 1) ** alpha / (avg_g + 1e-9), 2.0))  # 200→2.0 に変更
    c = 0.1
    max_step = 0.02  # 1ステップでパラメータが動く最大量（正規化空間）
    print(f"[spsa] a={a:.5f}  c={c}  avg_grad={avg_g:.6f}  max_step={max_step}", flush=True)
    print(f"[spsa] 初期損失 = {compute_loss(positions[:batch_size], weights):.2f}", flush=True)

    # 定期チェック用サブセット（全件評価によるハングを防ぐ）
    eval_subset = random.sample(positions, min(10000, len(positions)))

    theta = list(theta_init)
    best_theta = list(theta)
    best_loss = compute_loss(eval_subset, weights)
    iteration = 0
    last_check = time.time()

    while time.time() < deadline:
        iteration += 1
        a_k = a / (A + iteration) ** alpha
        c_k = c / iteration ** gamma

        delta = [random.choice([-1, 1]) for _ in range(n)]
        theta_p = [_clamp(theta[i] + c_k * delta[i], 0.0, 1.0) for i in range(n)]
        theta_m = [_clamp(theta[i] - c_k * delta[i], 0.0, 1.0) for i in range(n)]

        Lp = _batch_loss(theta_p)
        Lm = _batch_loss(theta_m)

        # 勾配推定 → パラメータ更新（勾配クリッピングで大きすぎる更新を防ぐ）
        for i in range(n):
            g_hat = (Lp - Lm) / (2.0 * c_k * delta[i] + 1e-12)
            update = _clamp(a_k * g_hat, -max_step, max_step)
            theta[i] = _clamp(theta[i] - update, 0.0, 1.0)

        # 50イテレーションごと or 5分ごとにサブセットで損失確認
        if iteration % 50 == 0 or time.time() - last_check > 300:
            full_loss = compute_loss(eval_subset, _from_norm(theta))
            elapsed   = (time.time() - start) / 3600
            remaining = max(0.0, deadline - time.time()) / 3600
            print(f"  iter={iteration:4d}  loss={full_loss:.2f}  a_k={a_k:.5f}"
                  f"  elapsed={elapsed:.2f}h  remaining={remaining:.2f}h", flush=True)
            if full_loss < best_loss:
                best_loss  = full_loss
                best_theta = list(theta)
                _save_yaml(_from_norm(best_theta), out_path)
                print(f"  [best updated] {best_loss:.2f}", flush=True)
            last_check = time.time()

    best_weights = _from_norm(best_theta)
    print(f"[spsa] 完了  iterations={iteration}  best_loss={best_loss:.2f}", flush=True)
    return best_weights


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
