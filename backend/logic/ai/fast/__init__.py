"""
Numba による高速探索エンジン。

find_best_move_fast() は logic.ai.search.find_best_move と同じ引数・戻り値で、
探索の中身（合法手生成・評価・PVS）をコンパイル済みコードで実行する。
numba が使えない環境では available() が False になり、呼び出し側は Python 版を使う。
"""

import os
import random
import threading
import time
from collections import Counter
from math import inf
from typing import Optional

import numpy as np

# GUNGI_FAST_ENGINE=0 で無効化できる（問題が起きたときに Python 版へ戻すため）
_ENABLED = os.getenv("GUNGI_FAST_ENGINE", "1") != "0"

try:
    if not _ENABLED:
        raise ImportError("disabled by GUNGI_FAST_ENGINE=0")
    from logic.ai.fast import core
    from logic.ai.fast.tables import (
        state_to_arrays, weights_to_arrays, decode_move, N_TYPES,
    )
    _AVAILABLE = True
except Exception:  # numba が入っていない・コンパイルできない環境
    _AVAILABLE = False

_ASP_DELTA = 50
_KILLER_ROWS = 18   # search.py の MAX_KILLER_DEPTH + 2 と同じ


# コンパイル（約 45 秒）が終わるまでは呼び出し側が Python 版を使う
_READY = False
# 置換表などの配列を共有するため、探索は同時に 1 つだけ行う
_LOCK = threading.Lock()


def available() -> bool:
    return _AVAILABLE


def ready() -> bool:
    return _AVAILABLE and _READY


class _Buffers:
    """置換表などの大きな配列は使い回す（毎手確保すると遅い）。"""

    def __init__(self):
        self.B = np.zeros((core.MAX_PLY, 9, 9, 3), np.int64)
        self.H = np.zeros((core.MAX_PLY, 9, 9), np.int64)
        self.HD = np.zeros((core.MAX_PLY, 2, N_TYPES), np.int64)
        self.SIDE = np.zeros(core.MAX_PLY, np.int64)
        self.OVER = np.zeros(core.MAX_PLY, np.int64)
        self.mbuf = np.zeros((core.MAX_PLY, core.MAX_MOVES_GEN), np.int64)
        self.path = np.zeros(core.MAX_PLY, np.uint64)
        self.tt_k = np.zeros(core.TT_SIZE, np.uint64)
        self.tt_i = np.zeros((core.TT_SIZE, 3), np.int64)
        self.tt_s = np.zeros(core.TT_SIZE, np.float64)
        self.ev_key = np.zeros(core.EV_SIZE, np.uint64)
        self.ev_val = np.zeros(core.EV_SIZE, np.float64)
        self.killers = np.zeros((_KILLER_ROWS, 2), np.int64)
        self.hist = np.zeros((9, 9, 9, 9), np.int64)

    def reset(self):
        self.tt_i[:, 0] = -1
        self.ev_val[:] = -1e18
        self.killers[:] = -1
        self.hist[:] = 0


_buf: Optional["_Buffers"] = None


def _buffers() -> "_Buffers":
    global _buf
    if _buf is None:
        _buf = _Buffers()
    _buf.reset()
    return _buf


def find_best_move_fast(
    state, ai_player: str, max_depth: int, time_limit: float,
    noise: int = 0, max_moves: int = 25, weights: Optional[dict] = None,
    return_score: bool = False, info: Optional[dict] = None,
):
    with _LOCK:
        return _find_best_move_locked(state, ai_player, max_depth, time_limit, noise,
                                      max_moves, weights, return_score, info)


def _find_best_move_locked(state, ai_player, max_depth, time_limit, noise, max_moves,
                           weights, return_score, info):
    start = time.time()
    b = _buffers()
    board, heights, hands, side = state_to_arrays(state)
    b.B[0], b.H[0], b.HD[0], b.SIDE[0], b.OVER[0] = board, heights, hands, side, 0
    ai = 0 if ai_player == "black" else 1
    P = np.array([state.rules.max_stack, 1 if state.rules.sui_can_tsuke else 0], np.int64)
    W, PV, HB, HR = weights_to_arrays(weights or {})

    gen = np.zeros(core.MAX_MOVES_GEN, np.int64)
    n = core.gen_moves(board, heights, hands, ai, P[0], P[1], gen, 0)
    if n == 0:
        return None
    # ルートは「取る駒の価値が高い順」に並べる（search._order_moves と同じ）
    moves = list(gen[:n])
    moves.sort(key=lambda m: -(core.ORDER_PV[(int(board[(m >> 12) & 0xF, (m >> 8) & 0xF,
                                                       heights[(m >> 12) & 0xF, (m >> 8) & 0xF] - 1]) - 1) >> 1]
                                if ((m >> 24) & 0xF) == 1 else 0))

    cnt = Counter(state.position_history)
    hist_keys = np.array(sorted(cnt), dtype=np.uint64)
    hist_cnt = np.array([cnt[k] for k in sorted(cnt)], dtype=np.int64)
    stats = np.zeros(2, np.int64)
    deadline = start + time_limit
    S = (b.B, b.H, b.HD, b.SIDE)

    best_move = moves[0]
    prev_score = 0.0
    completed = 0
    for depth in range(1, max_depth + 1):
        asp = _ASP_DELTA
        lo = -inf if depth == 1 else prev_score - asp
        hi = inf if depth == 1 else prev_score + asp
        scored = None
        for attempt in range(4):
            if attempt == 3:
                lo, hi = -inf, inf
            root = np.array(moves, np.int64)
            scores = np.zeros(len(moves), np.float64)
            ok = core.search_root(S, ai, depth, lo, hi, root, len(moves), scores, b.OVER, P, W, PV, HB, HR,
                                  b.tt_k, b.tt_i, b.tt_s, b.killers, b.hist, b.ev_key, b.ev_val,
                                  b.path, hist_keys, hist_cnt, stats, deadline, b.mbuf, max_moves)
            if not ok:
                break
            best_s = float(scores.max())
            if depth > 1 and attempt < 3:
                if best_s <= lo:
                    asp *= 2
                    lo = prev_score - asp
                    continue
                if best_s >= hi:
                    asp *= 2
                    hi = prev_score + asp
                    continue
            scored = list(zip(scores.tolist(), moves))
            prev_score = best_s
            break
        if scored is None:
            break
        completed = depth
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[0][0]
        if noise > 0 and top < 90_000:
            best_move = random.choice([m for s, m in scored if s >= top - noise])
        else:
            best_move = scored[0][1]
        moves = [best_move] + [m for m in moves if m != best_move]

    if info is not None:
        info["depth"] = completed
        info["root_moves"] = n
        info["score"] = prev_score
        info["nodes"] = int(stats[0])
    move = decode_move(best_move)
    if return_score:
        return move, prev_score
    return move


def warmup() -> None:
    """コンパイルを済ませて使える状態にする（約 45 秒）。"""
    global _READY
    if not _AVAILABLE or _READY:
        return
    from logic.game_engine import create_initial_state
    from logic.ai.weights import load_weights
    s = create_initial_state("nyumon", "ai_vs_ai", None, "easy", "easy")
    find_best_move_fast(s, "black", max_depth=2, time_limit=300.0, max_moves=15,
                        weights=load_weights("tier2"))
    _READY = True


def start_background_warmup() -> None:
    """サーバー起動時に呼ぶ。コンパイル中のリクエストは Python 版で処理される。"""
    if _AVAILABLE and not _READY:
        threading.Thread(target=_safe_warmup, daemon=True).start()


def _safe_warmup() -> None:
    global _AVAILABLE
    try:
        warmup()
    except Exception:
        _AVAILABLE = False   # コンパイルできなかったら以後は Python 版を使う
