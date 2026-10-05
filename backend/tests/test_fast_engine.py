"""Numba 版エンジンが Python 版と同じ合法手・指し手結果・ハッシュ・評価値を出すことの確認"""

import random

import numpy as np
import pytest

from logic.ai import fast
from logic.ai.fast import core
from logic.ai.fast.tables import state_to_arrays, weights_to_arrays, decode_move, PT_INDEX
from logic.ai.search import get_all_game_moves, _make_search_copy, _apply_move_inplace
from logic.ai.evaluate import evaluate
from logic.ai.weights import load_weights
from logic.game_engine import create_initial_state
from logic.ai.engine import get_ai_move_and_apply
from logic.zobrist import HASHER

pytestmark = pytest.mark.skipif(not fast.available(), reason="numba が使えない環境")

W2 = load_weights("tier2")


def _positions(seed: int, n_plies: int = 60):
    """ランダムな手で進めた局面を集める（全ルール）。"""
    rng = random.Random(seed)
    out = []
    for level in ("nyumon", "shokyuu", "chukyuu", "joukyuu"):
        s = create_initial_state(level, "ai_vs_ai", None, "easy", "easy")
        while s.phase == "setup":
            get_ai_move_and_apply(s)
        for _ in range(n_plies):
            moves = get_all_game_moves(s, s.current_player)
            if not moves or s.game_over:
                break
            ns = _make_search_copy(s)
            _apply_move_inplace(ns, rng.choice(moves))
            if ns.game_over:
                break
            s.board, s.hand_pieces, s.current_player = ns.board, ns.hand_pieces, ns.current_player
            out.append(_make_search_copy(s))
    return out


def _to_py(board, heights, hands):
    bd = [[[(PT_INDEX_INV[(int(board[r, c, k]) - 1) >> 1], "black" if (int(board[r, c, k]) - 1) & 1 == 0 else "white")
            for k in range(int(heights[r, c]))] for c in range(9)] for r in range(9)]
    hd = {o: sorted(PT_INDEX_INV[t].value for t in range(14) for _ in range(int(hands[i, t])))
          for i, o in enumerate(("black", "white"))}
    return bd, hd


PT_INDEX_INV = {i: pt for pt, i in PT_INDEX.items()}


def _py_board(state):
    bd = [[[(p.type, p.owner) for p in st] for st in row] for row in state.board]
    hd = {o: sorted(p.type.value for p in state.hand_pieces[o]) for o in ("black", "white")}
    return bd, hd


@pytest.mark.parametrize("seed", range(6))
def test_moves_make_hash_eval_match_python(seed):
    W, PV, HB, HR = weights_to_arrays(W2)
    buf = np.zeros(core.MAX_MOVES_GEN, np.int64)
    for s in _positions(seed):
        board, heights, hands, side = state_to_arrays(s)
        ms, mc = s.rules.max_stack, 1 if s.rules.sui_can_tsuke else 0
        # ハッシュ
        assert int(core.compute_hash(board, heights, hands, side)) == HASHER.hash_state(s)
        # 評価値（両陣営視点）
        for ai, name in ((0, "black"), (1, "white")):
            v = core.evaluate(board, heights, hands, ai, ms, mc, W, PV, HB, HR)
            assert abs(v - evaluate(s, name, W2)) < 1e-6
        # 合法手
        n = core.gen_moves(board, heights, hands, side, ms, mc, buf, 0)
        fast_moves = [decode_move(m) for m in buf[:n]]
        assert sorted(fast_moves) == sorted(get_all_game_moves(s, s.current_player))
        # 指し手の適用
        for m_int, m in zip(buf[:n], fast_moves):
            b2, h2, hd2 = board.copy(), heights.copy(), hands.copy()
            core.make_move(b2, h2, hd2, side, m_int)
            ns = _make_search_copy(s)
            _apply_move_inplace(ns, m)
            assert _to_py(b2, h2, hd2) == _py_board(ns)


def test_fast_search_finds_sui_capture():
    from tests.test_ai import _tactic_state
    s = _tactic_state()
    for d in (1, 3, 5):
        best = fast.find_best_move_fast(s, "black", max_depth=d, time_limit=20, max_moves=15, weights=W2)
        assert best[:5] == ("board", 5, 4, 4, 4)


def test_fast_search_same_depth_matches_python_score():
    """同じ深さでの最善評価値が Python 版と一致する（探索アルゴリズムの移植確認）。"""
    from logic.ai.search import find_best_move
    for s in _positions(99, 12)[::4]:
        pi, fi = {}, {}
        find_best_move(s, s.current_player, max_depth=2, time_limit=1e9, max_moves=15, weights=W2, info=pi)
        fast.find_best_move_fast(s, s.current_player, max_depth=2, time_limit=1e9, max_moves=15,
                                 weights=W2, info=fi)
        assert abs(pi["score"] - fi["score"]) < 1e-6
