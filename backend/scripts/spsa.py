"""
spsa.py: 評価関数の重みを、対局の勝敗で直接調整する（SPSA）。

毎回、全パラメータを ±c だけランダムな向きにずらした 2 つの重み（θ+ と θ-）で
先後を入れ替えて 2 局指し、勝った側の向きへ少しずつ動かす。
Texel 法（評価値と勝敗の誤差を小さくする）と違い、「勝つこと」そのものを目的にできる。

    python -m scripts.spsa --base tier2 --pairs 3000 --workers 4 --time 0.05 --out /tmp/spsa.yaml

途中経過は --out に随時保存される。採用判断は arena で行う。
"""

import argparse
import copy
import json
import os
import random
import sys
import time
from multiprocessing import Pool

import numpy as np
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (YAML のキー, ずらす幅 c, 最小, 最大)
PARAMS = [(f"piece_values.{k}", c, 10, 1500) for k, c in
          (("TAI", 30), ("CHU", 30), ("OZU", 20), ("TSU", 20), ("KIB", 12), ("YAR", 15), ("YUM", 15),
           ("SHO", 15), ("SAM", 15), ("SHI", 12), ("BOU", 10), ("TOR", 10), ("HYO", 6))] + [
    ("hand_piece_ratio.opening", 0.15, 0.3, 3.0),
    ("hand_piece_ratio.middle", 0.15, 0.3, 3.0),
    ("hand_piece_ratio.endgame", 0.15, 0.3, 3.0),
    ("center_weight", 1.0, 0, 30),
    ("forward_weight", 1.0, 0, 30),
    ("mobility_weight", 1.0, 0, 30),
    ("jumping_threat_weight", 4, 0, 150),
    ("jumping_sui_threat_weight", 30, 0, 800),
    ("sui_fortress_weight", 4, 0, 150),
    ("sui_safety_penalty", 10, 0, 400),
    ("isolated_penalty_ratio", 0.02, 0, 0.5),
    ("bou_defect_weight", 0.15, 0, 3),
    ("hanging_penalty_ratio", 0.03, 0, 1),
    ("frontline_weight", 4, 0, 100),
]


def _get(w, path):
    cur = w
    for k in path.split("."):
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    return cur


def _set(w, path, v):
    keys = path.split(".")
    cur = w
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    cur[keys[-1]] = v


def _weights(base, theta):
    w = copy.deepcopy(base)
    for (path, _c, lo, hi), v in zip(PARAMS, theta):
        _set(w, path, float(min(hi, max(lo, v))))
    return w


def _game(level, seed, w_black, w_white, tl, max_plies):
    """1 局指して黒から見た得点（勝=1, 分=0.5, 負=0）を返す。"""
    from logic.game_engine import create_initial_state, apply_move, apply_arata, apply_boushou
    from logic.ai.engine import _handle_setup
    from logic.ai.search import get_all_game_moves
    from logic.ai import fast
    rng = random.Random(seed)
    random.seed(seed)
    s = create_initial_state(level, "ai_vs_ai", None, "hard", "hard")
    while s.phase == "setup":
        _handle_setup(s, s.current_player)
    plies = 0
    while not s.game_over and plies < max_plies:
        if plies < 2:
            ms = [m for m in get_all_game_moves(s, s.current_player) if m[0] in ("board", "arata")]
            m = rng.choice(ms)
        else:
            w = w_black if s.current_player == "black" else w_white
            m = fast.find_best_move_fast(s, s.current_player, max_depth=30, time_limit=tl,
                                         max_moves=15, weights=w)
        if m is None:
            break
        fn = apply_move if m[0] == "board" else apply_arata if m[0] == "arata" else apply_boushou
        ok, _ = fn(s, *m[1:])
        if not ok:
            return 0.0 if s.current_player == "black" else 1.0
        plies += 1
    if s.game_over and s.winner:
        return 1.0 if s.winner == "black" else 0.0
    return 0.5


def _pair(args):
    """θ+ と θ- で先後を入れ替えて 2 局。θ+ の得点 − θ- の得点（-1〜1）を返す。"""
    from logic.ai import fast
    fast.warmup()
    level, seed, wp, wm, tl, max_plies = args
    a = _game(level, seed, wp, wm, tl, max_plies)          # θ+ が黒
    b = 1.0 - _game(level, seed, wm, wp, tl, max_plies)    # θ+ が白
    return (a + b) - 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="tier2")
    ap.add_argument("--resume", help="途中経過の JSON（--out と同じ名前の .json）から再開")
    ap.add_argument("--pairs", type=int, default=3000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--time", type=float, default=0.05)
    ap.add_argument("--max-plies", type=int, default=200)
    ap.add_argument("--lr", type=float, default=0.6, help="1 組あたりの移動量（c に対する倍率）")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from logic.ai.weights import load_weights
    base = copy.deepcopy(load_weights(a.base))
    theta = np.array([float(_get(base, p)) for p, *_ in PARAMS])
    c = np.array([p[1] for p in PARAMS], float)
    start = 0
    state_path = a.out + ".json"
    if os.path.exists(state_path):
        st = json.load(open(state_path))
        theta, start = np.array(st["theta"]), st["done"]
        print(f"resume from pair {start}", flush=True)
    levels = ["nyumon", "shokyuu", "chukyuu", "joukyuu"]
    rng = np.random.default_rng(a.seed + start)
    t0 = time.time()
    total = 0.0
    with Pool(a.workers) as pool:
        k = start
        while k < a.pairs:
            batch = []
            deltas = []
            for j in range(a.workers):
                d = rng.choice([-1.0, 1.0], size=len(theta))
                wp = _weights(base, theta + c * d)
                wm = _weights(base, theta - c * d)
                batch.append((levels[(k + j) % 4], a.seed * 1000003 + k + j, wp, wm, a.time, a.max_plies))
                deltas.append(d)
            results = pool.map(_pair, batch)
            # 学習率は後半ほど小さく（揺れを抑える）
            lr = a.lr * (1 - 0.7 * k / a.pairs)
            for d, r in zip(deltas, results):
                theta = theta + lr * c * r * d
                total += r
            for i, (_p, _c, lo, hi) in enumerate(PARAMS):
                theta[i] = min(hi, max(lo, theta[i]))
            k += len(batch)
            if k % 40 < a.workers:
                with open(a.out, "w", encoding="utf-8") as f:
                    yaml.safe_dump(_weights(base, theta), f, allow_unicode=True, sort_keys=False)
                json.dump({"theta": theta.tolist(), "done": k}, open(state_path, "w"))
                print(f"pairs={k} {time.time() - t0:.0f}s lr={lr:.3f} " +
                      " ".join(f"{p.split('.')[-1]}={v:.3g}" for (p, *_), v in zip(PARAMS, theta)), flush=True)
    with open(a.out, "w", encoding="utf-8") as f:
        yaml.safe_dump(_weights(base, theta), f, allow_unicode=True, sort_keys=False)
    json.dump({"theta": theta.tolist(), "done": k}, open(state_path, "w"))
    print("done", a.out)


if __name__ == "__main__":
    main()
