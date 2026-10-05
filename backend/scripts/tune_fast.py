"""
tune_fast.py: 高速エンジンの自己対戦で局面を集め、評価関数の重みを調整する（Texel 法）。

1. 局面生成（自己対戦、全ルール）:
    python -m scripts.tune_fast gen --games 400 --workers 3 --time 0.15 --out /tmp/pos.npz
2. 重みの調整（座標降下法、評価は Numba で一括計算）:
    python -m scripts.tune_fast tune --positions /tmp/pos.npz --base tier2 --out logic/ai/weights/tier3.yaml
3. 採用判断は arena で行う（例: --a weights=tier3 --b weights=tier2）。

損失: mean((結果 - sigmoid(黒視点の評価値 / K))^2)  結果は 黒勝=1, 引分=0.5, 白勝=0
"""

import argparse
import copy
import os
import random
import sys
import time
from multiprocessing import Pool

import numpy as np
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 局面生成 ─────────────────────────────────────────────────────────────────

def _play(args):
    level, seed, tl, noise, skip = args
    random.seed(seed)
    from logic.game_engine import create_initial_state, apply_move, apply_arata, apply_boushou
    from logic.ai.engine import _handle_setup
    from logic.ai import fast
    from logic.ai.fast.tables import state_to_arrays
    from logic.ai.weights import load_weights
    fast.warmup()
    w = load_weights("tier2")
    s = create_initial_state(level, "ai_vs_ai", None, "hard", "hard")
    while s.phase == "setup":
        _handle_setup(s, s.current_player)
    rec = []
    plies = 0
    while not s.game_over and plies < 200:
        if plies >= skip:
            b, h, hd, side = state_to_arrays(s)
            rec.append((b, h, hd, s.rules.max_stack, 1 if s.rules.sui_can_tsuke else 0))
        m = fast.find_best_move_fast(s, s.current_player, max_depth=20, time_limit=tl,
                                     noise=noise, max_moves=15, weights=w)
        if m is None:
            break
        fn = apply_move if m[0] == "board" else apply_arata if m[0] == "arata" else apply_boushou
        ok, _ = fn(s, *m[1:])
        if not ok:
            break
        plies += 1
    if s.game_over and s.winner:
        res = 1.0 if s.winner == "black" else 0.0
    else:
        res = 0.5
    return rec, res


def gen(a):
    levels = ["nyumon", "shokyuu", "chukyuu", "joukyuu"]
    jobs = [(levels[i % 4], a.seed * 100000 + i, a.time, a.noise, a.skip) for i in range(a.games)]
    B, H, HD, P, R = [], [], [], [], []
    t0 = time.time()
    with Pool(a.workers) as pool:
        for k, (rec, res) in enumerate(pool.imap_unordered(_play, jobs), 1):
            for b, h, hd, ms, st in rec:
                B.append(b); H.append(h); HD.append(hd); P.append((ms, st)); R.append(res)
            if k % 20 == 0:
                print(f"games={k} positions={len(R)} {time.time() - t0:.0f}s", flush=True)
    np.savez_compressed(a.out, B=np.array(B), H=np.array(H), HD=np.array(HD),
                        P=np.array(P, np.int64), R=np.array(R, np.float64))
    print(f"saved {len(R)} positions to {a.out}")


# ── 調整 ─────────────────────────────────────────────────────────────────────

# (YAML のキー, 1 ステップ, 最小, 最大)
PARAMS = [(f"piece_values.{k}", 10, 10, 1500) for k in
          ("TAI", "CHU", "OZU", "TSU", "KIB", "YAR", "YUM", "SHO", "SAM", "SHI", "BOU", "TOR", "HYO")] + [
    ("hand_piece_ratio.opening", 0.05, 0.3, 2.5),
    ("hand_piece_ratio.middle", 0.05, 0.3, 2.5),
    ("hand_piece_ratio.endgame", 0.05, 0.3, 2.5),
    ("center_weight", 0.5, 0, 30),
    ("forward_weight", 0.5, 0, 30),
    ("mobility_weight", 0.5, 0, 30),
    ("jumping_threat_weight", 2, 0, 100),
    ("jumping_sui_threat_weight", 10, 0, 600),
    ("sui_fortress_weight", 2, 0, 100),
    ("sui_safety_penalty", 5, 0, 300),
    ("isolated_penalty_ratio", 0.01, 0, 0.5),
    ("bou_defect_weight", 0.05, 0, 2),
    ("hanging_penalty_ratio", 0.02, 0, 1),
    ("frontline_weight", 2, 0, 80),
    ("stack_height_bonus.1", 0.05, 1.0, 3.0),
    ("stack_height_bonus.2", 0.05, 1.0, 3.0),
]


def _get(w, path):
    cur = w
    for k in path.split("."):
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    return cur


def _set(w, path, v):
    w = copy.deepcopy(w)
    keys = path.split(".")
    cur = w
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    last = keys[-1]
    if isinstance(cur, list):
        cur[int(last)] = v
    else:
        cur[last] = v
    return w


def tune(a):
    from numba import njit, prange  # noqa: F401
    from logic.ai.fast import core
    from logic.ai.fast.tables import weights_to_arrays
    from logic.ai.weights import load_weights

    d = np.load(a.positions)
    B, H, HD, P, R = d["B"], d["H"], d["HD"], d["P"], d["R"]
    n = len(R)
    print(f"positions={n} (black win {np.mean(R == 1):.2f}, draw {np.mean(R == 0.5):.2f})", flush=True)

    @njit(cache=False)
    def eval_all(B, H, HD, P, W, PV, HB, HR, out):
        for i in range(B.shape[0]):
            out[i] = core.evaluate(B[i], H[i], HD[i], 0, P[i, 0], P[i, 1], W, PV, HB, HR)

    evals = np.zeros(n)

    def loss(w, K):
        Wa, PVa, HBa, HRa = weights_to_arrays(w)
        eval_all(B, H, HD, P, Wa, PVa, HBa, HRa, evals)
        e = 1.0 / (1.0 + 10 ** (-np.clip(evals, -30000, 30000) / K))
        return float(np.mean((R - e) ** 2))

    w = copy.deepcopy(load_weights(a.base))
    # K（評価値→勝率の尺度）を先に合わせる
    best_k, best_l = None, 9
    for K in (100, 150, 200, 300, 400, 600, 800, 1200, 1600, 2400, 3200, 4800, 6400, 9600):
        L = loss(w, K)
        if L < best_l:
            best_k, best_l = K, L
    K = best_k
    print(f"K={K} initial loss={best_l:.6f}", flush=True)
    cur = best_l
    deadline = time.time() + a.hours * 3600
    for it in range(1, 1000):
        changed = 0
        for path, step, lo, hi in PARAMS:
            v = _get(w, path)
            for cand in (min(hi, v + step), max(lo, v - step)):
                if cand == v:
                    continue
                w2 = _set(w, path, cand)
                L = loss(w2, K)
                if L < cur - 1e-9:
                    w, cur, changed = w2, L, changed + 1
                    break
            if time.time() > deadline:
                break
        print(f"iter={it} loss={cur:.6f} changed={changed}", flush=True)
        with open(a.out, "w", encoding="utf-8") as f:
            yaml.safe_dump(w, f, allow_unicode=True, sort_keys=False)
        if changed == 0 or time.time() > deadline:
            break
    print("done", a.out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--games", type=int, default=400)
    g.add_argument("--workers", type=int, default=3)
    g.add_argument("--time", type=float, default=0.15)
    g.add_argument("--noise", type=int, default=30)
    g.add_argument("--skip", type=int, default=6, help="序盤の何手を記録しないか")
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--out", required=True)
    t = sub.add_parser("tune")
    t.add_argument("--positions", required=True)
    t.add_argument("--base", default="tier2")
    t.add_argument("--hours", type=float, default=1.0)
    t.add_argument("--out", required=True)
    a = ap.parse_args()
    gen(a) if a.cmd == "gen" else tune(a)


if __name__ == "__main__":
    main()
