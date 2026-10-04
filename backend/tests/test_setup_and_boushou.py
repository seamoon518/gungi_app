"""A4: 謀の寝返り / A5: 中級・上級の初期配置フェーズ"""

import pytest

from logic.game_engine import (
    create_initial_state, apply_setup_place, apply_setup_done, apply_boushou, apply_move,
)
from logic.setup import get_valid_setup_positions
from logic.ai.search import get_all_game_moves
from tests.helpers import make_state, stack_at


# ── A5: 初期配置フェーズ ─────────────────────────────────────────────────────

@pytest.mark.parametrize("level", ["chukyuu", "joukyuu"])
def test_setup_requires_sui_first_and_own_territory(level):
    s = create_initial_state(level)
    ok, _ = apply_setup_place(s, "大", 8, 0)
    assert not ok                               # 帥より先に置けない
    ok, _ = apply_setup_place(s, "帥", 5, 4)
    assert not ok                               # 自陣(7〜9段目)の外
    ok, err = apply_setup_place(s, "帥", 8, 4)
    assert ok, err
    assert s.current_player == "white"
    assert set(get_valid_setup_positions(s.board, "white", s.rules.max_stack)) == {
        (r, c) for r in range(3) for c in range(9)}
    ok, err = apply_setup_place(s, "帥", 0, 4)
    assert ok, err
    assert s.current_player == "black"
    # 帥の上にはツケられない
    assert (8, 4) not in get_valid_setup_positions(s.board, "black", s.rules.max_stack)


def test_setup_done_order_black_first():
    s = create_initial_state("chukyuu")
    apply_setup_place(s, "帥", 8, 4)
    apply_setup_place(s, "帥", 0, 4)
    ok, err = apply_setup_done(s)               # 黒が済
    assert ok, err
    assert s.current_player == "white" and s.phase == "setup"
    for col in (0, 1, 2):                       # 白は続けて置ける
        ok, err = apply_setup_place(s, "兵", 1, col)
        assert ok, err
        assert s.current_player == "white"
    ok, err = apply_setup_done(s)               # 白が済 → 対局開始
    assert ok, err
    assert s.phase == "play" and s.current_player == "black"


def test_setup_white_done_starts_game_immediately():
    s = create_initial_state("joukyuu")
    apply_setup_place(s, "帥", 8, 4)
    apply_setup_place(s, "帥", 0, 4)
    apply_setup_place(s, "大", 8, 3)
    ok, err = apply_setup_done(s)               # 白が先に済
    assert ok, err
    assert s.phase == "play" and s.current_player == "black"


def test_setup_done_before_sui_rejected():
    s = create_initial_state("chukyuu")
    ok, _ = apply_setup_done(s)
    assert not ok and s.phase == "setup" and s.current_player == "black"


def test_setup_blocks_moves():
    s = create_initial_state("chukyuu")
    apply_setup_place(s, "帥", 8, 4)
    ok, _ = apply_move(s, 8, 4, 7, 4)
    assert not ok


# ── A4: 謀の寝返り ──────────────────────────────────────────────────────────

def _bou_state(dest, hand, level="joukyuu", src=None):
    cells = {(5, 4): src or [("謀", "black")], (4, 3): dest,
             (8, 0): [("帥", "black")], (0, 8): [("帥", "white")]}
    return make_state(cells, level=level, hand={"black": hand})


def test_boushou_swaps_enemy_with_hand_piece():
    s = _bou_state([("兵", "white")], ["兵", "小"])
    ok, err = apply_boushou(s, 5, 4, 4, 3, 0)
    assert ok, err
    assert stack_at(s, 4, 3) == [("兵", "black"), ("謀", "black")]
    assert stack_at(s, 5, 4) == []
    assert [p.type.value for p in s.hand_pieces["black"]] == ["小"]
    assert s.current_player == "white"


def test_boushou_lower_layer_in_three_stack():
    s = _bou_state([("槍", "white"), ("兵", "white")], ["槍"],
                   src=[("兵", "black"), ("謀", "black")])
    ok, err = apply_boushou(s, 5, 4, 4, 3, 0)
    assert ok, err
    assert stack_at(s, 4, 3) == [("槍", "black"), ("兵", "white"), ("謀", "black")]


@pytest.mark.parametrize("dest,hand,idx,src", [
    ([("兵", "white")], ["小"], 0, None),                          # 同種の手駒なし
    ([("兵", "black")], ["兵"], 0, None),                          # 対象が自駒（ツケ扱い不可）
    ([("兵", "white")], ["兵"], 3, None),                          # インデックス範囲外
    ([("兵", "white")], ["兵"], -1, None),                         # 負のインデックス
    ([("兵", "white"), ("兵", "white")], ["兵"], 0, None),          # 自分(1段)より高い
    ([("兵", "white")], ["兵"], 0, [("兵", "black")]),             # 動かす駒が謀でない
])
def test_boushou_rejected(dest, hand, idx, src):
    s = _bou_state(dest, hand, src=src)
    before = [stack_at(s, r, c) for r in range(9) for c in range(9)]
    ok, _ = apply_boushou(s, 5, 4, 4, 3, idx)
    assert not ok
    assert [stack_at(s, r, c) for r in range(9) for c in range(9)] == before
    assert s.current_player == "black"


def test_ai_move_generator_includes_boushou():
    s = _bou_state([("兵", "white")], ["兵"])
    moves = get_all_game_moves(s, "black")
    assert ("boushou", 5, 4, 4, 3, 0) in moves
    assert ("board", 5, 4, 4, 3, "tsuke_enemy") in moves
    assert ("board", 5, 4, 4, 3, "capture") in moves
