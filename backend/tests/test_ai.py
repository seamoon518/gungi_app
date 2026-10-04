"""A8: AI の手の合法性 / A11: 探索の千日手カウンタ"""

import time
from collections import Counter
from math import inf

import pytest

from logic.game_engine import create_initial_state
from logic.ai import engine as ai_engine
from logic.ai.engine import get_ai_move_and_apply
from logic.ai.search import (
    pvs, find_best_move, TranspositionTable, KillerMoves, HistoryTable,
)
from logic.ai.weights import load_weights

LEVELS = ["nyumon", "shokyuu", "chukyuu", "joukyuu"]
DIFFS = ["easy", "normal", "hard"]


@pytest.fixture
def fast_ai(monkeypatch):
    fast = {k: {**v, "time_limit": 0.3} for k, v in ai_engine._DIFFICULTY_PARAMS.items()}
    monkeypatch.setattr(ai_engine, "_DIFFICULTY_PARAMS", fast)


@pytest.mark.slow
@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("diff", DIFFS)
def test_ai_vs_ai_moves_are_legal(level, diff, fast_ai):
    """配置フェーズ + 対局 20 手を AI 同士で進め、すべて合法（apply が成功）であること。"""
    s = create_initial_state(level, "ai_vs_ai", None, diff, diff)
    plies = 0
    for _ in range(200):
        if s.game_over or plies >= 20:
            break
        was_play = s.phase == "play"
        before = s.current_player
        ok, err = get_ai_move_and_apply(s)
        assert ok, f"{level}/{diff}: {err}"
        if was_play:
            plies += 1
            assert s.game_over or s.current_player != before
    assert s.phase == "play"
    assert plies == 20 or s.game_over


@pytest.mark.parametrize("human", ["black", "white"])
def test_ai_setup_in_ai_mode_reaches_play(human, fast_ai):
    from logic.game_engine import apply_setup_place, apply_setup_done
    s = create_initial_state("chukyuu", "ai", "easy", human_player=human)
    for _ in range(100):
        if s.phase == "play":
            break
        if s.current_player == s.ai_player:
            ok, err = get_ai_move_and_apply(s)
            assert ok, err
        else:
            row = 8 if human == "black" else 0
            from logic.setup import has_placed_sui
            if not has_placed_sui(s.board, human):
                ok, err = apply_setup_place(s, "帥", row, 4)
            else:
                ok, err = apply_setup_done(s)
            assert ok, err
    assert s.phase == "play"


def _pvs_counter_after_search(depth, time_limit=30.0):
    s = create_initial_state("nyumon", "ai_vs_ai", None, "easy", "easy")
    counter: Counter = Counter()
    pvs(s, "black", depth, -inf, inf, time.time(), time_limit, 15,
        TranspositionTable(), KillerMoves(), HistoryTable(), load_weights("tier2"),
        position_counter=Counter(s.position_history), search_path_counter=counter)
    return counter


@pytest.mark.parametrize("depth", [1, 2, 3])
def test_search_path_counter_is_balanced(depth):
    """H3: 探索が終わったら探索パスのカウンタはすべて 0 に戻っていること。"""
    counter = _pvs_counter_after_search(depth)
    leaked = {k: v for k, v in counter.items() if v != 0}
    assert not leaked, f"{len(leaked)} 局面のカウンタが残留 (合計 {sum(leaked.values())})"


def test_search_path_counter_balanced_after_timeout():
    counter = Counter()
    s = create_initial_state("nyumon", "ai_vs_ai", None, "easy", "easy")
    with pytest.raises(TimeoutError):
        pvs(s, "black", 6, -inf, inf, time.time(), 0.05, 15,
            TranspositionTable(), KillerMoves(), HistoryTable(), load_weights("tier2"),
            position_counter=Counter(s.position_history), search_path_counter=counter)
    assert all(v == 0 for v in counter.values())


def test_find_best_move_returns_legal_move_quickly():
    s = create_initial_state("nyumon", "ai_vs_ai", None, "easy", "easy")
    t0 = time.time()
    best = find_best_move(s, "black", max_depth=3, time_limit=1.0, max_moves=15,
                          weights=load_weights("tier2"))
    assert best is not None and time.time() - t0 < 3.0


# ── 戦術テスト: 探索の誤評価で明白な手を逃さないこと ─────────────────────────

def _tactic_state():
    from tests.helpers import make_state
    # 黒の槍(5,4)が白の帥(4,4)を取れる。黒の帥(8,0)は安全、白に反撃手段なし。
    return make_state({
        (5, 4): [("槍", "black")], (4, 4): [("帥", "white")],
        (8, 0): [("帥", "black")], (0, 8): [("兵", "white")],
        (6, 6): [("兵", "black")], (2, 2): [("兵", "white")],
    }, level="nyumon", mode="ai_vs_ai", ai_player="both")


@pytest.mark.parametrize("max_depth", [1, 2, 4, 6])
def test_ai_captures_sui_when_possible(max_depth):
    s = _tactic_state()
    best = find_best_move(s, "black", max_depth=max_depth, time_limit=20.0,
                          max_moves=15, weights=load_weights("tier2"))
    assert best[:5] == ("board", 5, 4, 4, 4), best


@pytest.mark.parametrize("diff", DIFFS)
def test_engine_captures_sui_each_difficulty(diff):
    s = _tactic_state()
    s.ai_difficulty_black = diff
    ok, err = get_ai_move_and_apply(s)
    assert ok, err
    assert s.game_over and s.winner == "black"


def test_root_scores_stay_correct_across_iterative_deepening():
    """H3: 反復深化を重ねても「帥を取る手」が勝ち評価のまま（0 点に化けない）こと。"""
    from logic.ai.search import (
        get_all_game_moves, _make_search_copy, _apply_move_inplace, _order_moves,
    )
    s = _tactic_state()
    w = load_weights("tier2")
    moves = _order_moves(get_all_game_moves(s, "black"), s.board)
    cap = ("board", 5, 4, 4, 4, "capture")
    counter, pc = Counter(), Counter(s.position_history)
    tt, km, hh = TranspositionTable(), KillerMoves(), HistoryTable()
    for depth in range(1, 6):
        scores = {}
        for m in moves:
            ns = _make_search_copy(s)
            _apply_move_inplace(ns, m)
            scores[m] = pvs(ns, "black", depth - 1, -inf, inf, time.time(), 60, 15,
                            tt, km, hh, w, position_counter=pc, search_path_counter=counter)
        assert scores[cap] >= 90_000, (depth, scores[cap])
        assert max(scores, key=scores.get) == cap, depth


def test_search_does_not_mutate_real_state():
    """探索用コピーは駒を共有するため、探索後に元の局面が変わっていないことを確認する。"""
    import copy
    s = create_initial_state("joukyuu", "ai_vs_ai", None, "easy", "easy")
    for _ in range(40):                       # 配置フェーズを進めて駒・手駒を揃える
        if s.phase == "play":
            break
        get_ai_move_and_apply(s)
    before_board = copy.deepcopy(s.board)
    before_hand = copy.deepcopy(s.hand_pieces)
    before_player = s.current_player
    find_best_move(s, s.current_player, max_depth=2, time_limit=5.0, max_moves=15,
                   weights=load_weights("tier2"))
    assert s.board == before_board and s.hand_pieces == before_hand
    assert s.current_player == before_player
