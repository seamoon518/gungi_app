"""
tune_eval.py: 評価関数の重みを、自己対戦の局面から調整する（Texel 法 + 探索値の蒸留）。

tune_fast.py との違い:
  - 局面ごとに「その局面で探索した評価値」も保存し、勝敗と混ぜた値を正解にする（勝敗だけだと雑音が大きい）
  - 取り合いの途中の局面を除く（静止探索の値と静的評価が一致する「静かな局面」だけを使う）
  - 評価は Numba の並列ループでまとめて計算する

1. 局面生成（高速エンジンで自己対戦。全ルール）:
    python -m scripts.tune_eval gen --games 3000 --workers 4 --time 0.1 --out /tmp/pos.npz
   （/tmp/pos.npz.part000.npz, part001, ... に 100 局ずつ保存。止まったら同じコマンドで続きから）
2. 重みの調整:
    python -m scripts.tune_eval tune --positions '/tmp/pos.npz.part*.npz' --base tier2 --out /tmp/tier3.yaml
3. 採用判断は arena で行う（例: --a weights=/tmp/tier3.yaml --b weights=tier2）
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
    level, seed, tl, noise, skip, weights_name = args
    random.seed(seed)
    from logic.game_engine import create_initial_state, apply_move, apply_arata, apply_boushou
    from logic.ai.engine import _handle_setup
    from logic.ai.search import get_all_game_moves
    from logic.ai import fast
    from logic.ai.fast.tables import state_to_arrays
    from logic.ai.weights import load_weights
    fast.warmup()
    w = load_weights(weights_name)
    s = create_initial_state(level, "ai_vs_ai", None, "hard", "hard")
    while s.phase == "setup":
        _handle_setup(s, s.current_player)
    rec = []
    plies = 0
    rng = random.Random(seed)
    while not s.game_over and plies < 200:
        if plies < 2:   # 序盤の 2 手はランダム（同じ対局ばかりにならないように）
            ms = [m for m in get_all_game_moves(s, s.current_player) if m[0] in ("board", "arata")]
            m = rng.choice(ms)
            score = None
        else:
            info = {}
            m = fast.find_best_move_fast(s, s.current_player, max_depth=30, time_limit=tl,
                                         noise=noise, max_moves=15, weights=w, info=info)
            score = info.get("score")
        if m is None:
            break
        if plies >= skip and score is not None and abs(score) < 5000:
            b, h, hd, side = state_to_arrays(s)
            black_score = score if side == 0 else -score
            rec.append((b, h, hd, s.rules.max_stack, 1 if s.rules.sui_can_tsuke else 0, side, black_score))
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
    """100 局ごとに {out}.partNNN.npz へ保存する（途中で止まっても集めた分は残る。再実行すると続きから）。"""
    import glob
    levels = ["nyumon", "shokyuu", "chukyuu", "joukyuu"]
    done_parts = sorted(glob.glob(a.out + ".part*.npz"))
    start = len(done_parts) * 100
    jobs = [(levels[i % 4], a.seed * 100000 + i, a.time, a.noise, a.skip, a.weights)
            for i in range(start, a.games)]
    buf = ([], [], [], [], [], [], [])
    part = len(done_parts)
    t0 = time.time()
    with Pool(a.workers) as pool:
        for k, (rec, res) in enumerate(pool.imap(_play, jobs), start + 1):
            for b, h, hd, ms, st, side, sc in rec:
                for lst, v in zip(buf, (b, h, hd, (ms, st), side, sc, res)):
                    lst.append(v)
            if k % 100 == 0 or k == a.games:
                _save(f"{a.out}.part{part:03d}.npz", *buf)
                print(f"games={k} part={part} positions={len(buf[0])} {time.time() - t0:.0f}s", flush=True)
                part += 1
                buf = ([], [], [], [], [], [], [])
    print("done")


def _save(path, B, H, HD, P, SIDE, S, R):
    np.savez_compressed(path, B=np.array(B), H=np.array(H), HD=np.array(HD),
                        P=np.array(P, np.int64), SIDE=np.array(SIDE, np.int64),
                        S=np.array(S, np.float64), R=np.array(R, np.float64))


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
    ("sui_mobility_weight", 2, 0, 80),
    ("ray_blocking_weight", 2, 0, 80),
    ("arata_control_weight", 2, 0, 80),
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


def _sig(x, k):
    return 1.0 / (1.0 + 10 ** (-np.clip(x, -30000, 30000) / k))


def tune(a):
    from numba import njit, prange
    from logic.ai.fast import core
    from logic.ai.fast.tables import weights_to_arrays, N_TYPES
    from logic.ai.weights import load_weights

    import glob
    files = sorted(sum((glob.glob(p) for p in a.positions), []))
    ds = [np.load(f) for f in files]
    B, H, HD, P, SIDE, S, R = (np.concatenate([d[k] for d in ds if len(d["R"])])
                               for k in ("B", "H", "HD", "P", "SIDE", "S", "R"))
    print(f"files={len(files)}", flush=True)
    n = len(R)
    print(f"positions={n} (black win {np.mean(R == 1):.2f}, draw {np.mean(R == 0.5):.2f})", flush=True)

    @njit(parallel=True, cache=False)
    def eval_all(B, H, HD, P, W, PV, HB, HR, out):
        for i in prange(B.shape[0]):
            out[i] = core.evaluate(B[i], H[i], HD[i], 0, P[i, 0], P[i, 1], W, PV, HB, HR)

    @njit(cache=False)
    def quiet_all(B, H, HD, P, SIDE, W, PV, HB, HR, out):
        mp = core.MAX_PLY
        Bs = np.zeros((mp, 9, 9, 3), np.int64)
        Hs = np.zeros((mp, 9, 9), np.int64)
        HDs = np.zeros((mp, 2, N_TYPES), np.int64)
        Ss = np.zeros(mp, np.int64)
        OV = np.zeros(mp, np.int64)
        mbuf = np.zeros((mp, core.MAX_MOVES_GEN), np.int64)
        ek = np.zeros(core.EV_SIZE, np.uint64)
        ev = np.full(core.EV_SIZE, -1e18)
        st = np.zeros(2, np.int64)
        PP = np.zeros(7, np.int64)
        for i in range(B.shape[0]):
            Bs[0] = B[i]; Hs[0] = H[i]; HDs[0] = HD[i]; Ss[0] = SIDE[i]
            PP[0] = P[i, 0]; PP[1] = P[i, 1]; PP[2] = 4
            q = core.quiescence(Bs, Hs, HDs, Ss, 0, 0, -1e9, 1e9, 4, OV, PP, W, PV, HB, HR,
                                ek, ev, st, 0.0, mbuf)
            out[i] = q

    w = copy.deepcopy(load_weights(a.base))
    Wa, PVa, HBa, HRa = weights_to_arrays(w)
    st = np.zeros(n)
    eval_all(B, H, HD, P, Wa, PVa, HBa, HRa, st)
    q = np.zeros(n)
    t0 = time.time()
    quiet_all(B, H, HD, P, SIDE, Wa, PVa, HBa, HRa, q)
    quiet = np.abs(q - st) < 1.0
    print(f"quiet positions {quiet.sum()} / {n} ({time.time() - t0:.0f}s)", flush=True)
    B, H, HD, P, S, R = B[quiet], H[quiet], HD[quiet], P[quiet], S[quiet], R[quiet]
    n = len(R)

    # 探索値の尺度（評価値→勝率）を勝敗から合わせ、正解 = λ*勝敗 + (1-λ)*探索値の勝率
    ks = min((100, 150, 200, 300, 400, 600, 800, 1200, 1600, 2400, 3200, 4800),
             key=lambda K: float(np.mean((R - _sig(S, K)) ** 2)))
    T = a.lam * R + (1 - a.lam) * _sig(S, ks)
    print(f"search-score K={ks} target mean={T.mean():.3f}", flush=True)

    evals = np.zeros(n)

    def loss(w, K):
        Wa, PVa, HBa, HRa = weights_to_arrays(w)
        eval_all(B, H, HD, P, Wa, PVa, HBa, HRa, evals)
        return float(np.mean((T - _sig(evals, K)) ** 2))

    K = min((100, 150, 200, 300, 400, 600, 800, 1200, 1600, 2400), key=lambda K: loss(w, K))
    cur = loss(w, K)
    base_loss = cur
    print(f"K={K} initial loss={cur:.6f}", flush=True)
    deadline = time.time() + a.hours * 3600
    scale = 1.0
    for it in range(1, 1000):
        changed = 0
        for path, step, lo, hi in PARAMS:
            try:
                v = _get(w, path)
            except (KeyError, IndexError, TypeError):
                continue
            st_ = step * scale
            for cand in (min(hi, v + st_), max(lo, v - st_)):
                if cand == v:
                    continue
                w2 = _set(w, path, round(cand, 4))
                L = loss(w2, K)
                if L < cur - 1e-9:
                    w, cur, changed = w2, L, changed + 1
                    break
            if time.time() > deadline:
                break
        print(f"iter={it} loss={cur:.6f} (start {base_loss:.6f}) changed={changed} scale={scale}", flush=True)
        with open(a.out, "w", encoding="utf-8") as f:
            yaml.safe_dump(w, f, allow_unicode=True, sort_keys=False)
        if time.time() > deadline:
            break
        if changed == 0:
            if scale <= 0.25:
                break
            scale /= 2
    print("done", a.out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--games", type=int, default=3000)
    g.add_argument("--workers", type=int, default=4)
    g.add_argument("--time", type=float, default=0.1)
    g.add_argument("--noise", type=int, default=20)
    g.add_argument("--skip", type=int, default=4, help="序盤の何手を記録しないか")
    g.add_argument("--weights", default="tier2")
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--out", required=True)
    t = sub.add_parser("tune")
    t.add_argument("--positions", nargs="+", required=True, help="npz ファイル（glob 可。例: '/tmp/pos.npz.part*.npz'）")
    t.add_argument("--base", default="tier2")
    t.add_argument("--lam", type=float, default=0.5, help="正解のうち勝敗の割合（残りは探索値）")
    t.add_argument("--hours", type=float, default=2.0)
    t.add_argument("--out", required=True)
    a = ap.parse_args()
    gen(a) if a.cmd == "gen" else tune(a)


if __name__ == "__main__":
    main()
