"""A1/A2/A3/A7: 初期配置・移動・ツケ・取る・新・勝敗・千日手"""

from collections import Counter

import pytest

from logic.game_engine import create_initial_state, apply_move, apply_arata
from logic.movement import get_valid_moves
from logic.arata import get_valid_arata_positions
from tests.helpers import make_state, stack_at, count_pieces


def _counter(pieces):
    return Counter(p.type.value for p in pieces)


# ── A1: 初期状態 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("level,board_n,hand_n,max_stack,sui_tsuke,phase", [
    ("nyumon", 13, 7, 2, False, "play"),
    ("shokyuu", 15, 7, 2, False, "play"),
    ("chukyuu", 0, 25, 2, True, "setup"),
    ("joukyuu", 0, 25, 3, True, "setup"),
])
def test_initial_state(level, board_n, hand_n, max_stack, sui_tsuke, phase):
    s = create_initial_state(level)
    assert s.phase == phase
    assert s.current_player == "black"
    assert s.rules.max_stack == max_stack
    assert s.rules.sui_can_tsuke is sui_tsuke
    for owner in ("black", "white"):
        assert count_pieces(s, owner) == board_n
        assert len(s.hand_pieces[owner]) == hand_n


def test_initial_piece_sets():
    # 入門: 特殊駒なし 20 枚 / 初級: 弓 2 枚を追加した 22 枚 / 中上級: 全 25 枚
    expected_full = Counter({"帥": 1, "大": 1, "中": 1, "小": 2, "侍": 2, "槍": 3, "馬": 2,
                             "忍": 2, "砦": 2, "兵": 4, "砲": 1, "筒": 1, "弓": 2, "謀": 1})
    for level, removed in [("nyumon", {"砲": 1, "筒": 1, "弓": 2, "謀": 1}),
                           ("shokyuu", {"砲": 1, "筒": 1, "謀": 1}),
                           ("chukyuu", {}), ("joukyuu", {})]:
        s = create_initial_state(level)
        for owner in ("black", "white"):
            on_board = [p for row in s.board for st in row for p in st if p.owner == owner]
            total = _counter(on_board) + _counter(s.hand_pieces[owner])
            assert total == expected_full - Counter(removed), (level, owner)


def test_initial_layout_is_point_symmetric():
    # 黒陣は白陣を 180° 回転した配置（初級編は仕様確認待ちのため対象外）
    for level in ("nyumon",):
        s = create_initial_state(level)
        for r in range(9):
            for c in range(9):
                w = [(p.type, p.owner) for p in s.board[r][c] if p.owner == "white"]
                b = [(p.type, p.owner) for p in s.board[8 - r][8 - c] if p.owner == "black"]
                assert [t for t, _ in w] == [t for t, _ in b], (level, r, c)


@pytest.mark.parametrize("mode,human,expected_ai", [
    ("pvp", None, None),
    ("ai", None, "white"),
    ("ai", "black", "white"),
    ("ai", "white", "black"),
    ("ai_vs_ai", None, "both"),
])
def test_ai_player_assignment(mode, human, expected_ai):
    s = create_initial_state("nyumon", mode, "easy", human_player=human)
    assert s.ai_player == expected_ai


# ── A2: 移動・ツケ・取る ─────────────────────────────────────────────────────

def _moves(state, r, c):
    o = get_valid_moves(state.board, r, c, state.rules.max_stack, state.rules.sui_can_tsuke)
    return set(o.valid_moves), set(o.enemy_tsuke_moves)


def test_hyo_basic_move_black_forward_is_row_decrease():
    s = create_initial_state("nyumon")
    valid, _ = _moves(s, 6, 0)
    assert valid == {(5, 0), (7, 0)}


def test_white_forward_is_row_increase():
    s = create_initial_state("nyumon")
    valid, _ = _moves(s, 2, 0)   # 白兵
    assert valid == {(3, 0), (1, 0)}


def test_path_blocking_and_no_tsuke_on_sui():
    s = create_initial_state("nyumon")
    # 黒槍(7,4): 前2マスは(6,4)の自駒で遮られる / 後ろは帥なのでツケ不可
    valid, _ = _moves(s, 7, 4)
    assert valid == {(6, 4), (6, 3), (6, 5)}


def test_cannot_capture_or_tsuke_higher_stack():
    s = make_state({(5, 4): [("兵", "black")],
                    (4, 4): [("兵", "white"), ("侍", "white")],
                    (8, 0): [("帥", "black")], (0, 8): [("帥", "white")]})
    valid, et = _moves(s, 5, 4)
    assert (4, 4) not in valid and (4, 4) not in et


def test_same_height_capture_and_tsuke_depends_on_max_stack():
    cells = {(5, 4): [("兵", "black"), ("槍", "black")],
             (4, 4): [("兵", "white"), ("侍", "white")],
             (8, 0): [("帥", "black")], (0, 8): [("帥", "white")]}
    nyumon = make_state(cells, level="nyumon")
    valid, et = _moves(nyumon, 5, 4)
    assert (4, 4) in valid and (4, 4) not in et      # 2段上限: 取れるがツケ不可
    joukyuu = make_state(cells, level="joukyuu")
    valid, et = _moves(joukyuu, 5, 4)
    assert (4, 4) in valid and (4, 4) in et          # 3段上限: ツケも可


def test_enemy_sui_can_be_captured_but_not_tsuked():
    s = make_state({(5, 4): [("兵", "black")], (4, 4): [("帥", "white")],
                    (8, 0): [("帥", "black")]})
    valid, et = _moves(s, 5, 4)
    assert (4, 4) in valid and (4, 4) not in et


@pytest.mark.parametrize("level,can_tsuke", [("nyumon", False), ("chukyuu", True)])
def test_shi_tsuke_rule(level, can_tsuke):
    s = make_state({(8, 4): [("帥", "black")], (7, 4): [("兵", "black")],
                    (0, 4): [("帥", "white")]}, level=level)
    valid, _ = _moves(s, 8, 4)
    assert ((7, 4) in valid) is can_tsuke
    assert (7, 3) in valid  # 空マスには常に動ける


def test_jump_piece_height_condition():
    base = {(8, 0): [("帥", "black")], (0, 8): [("帥", "white")]}
    s = make_state({**base, (6, 4): [("弓", "black")], (5, 4): [("兵", "white")]})
    valid, _ = _moves(s, 6, 4)
    assert (4, 4) in valid                      # 1段の駒は飛び越せる
    s2 = make_state({**base, (6, 4): [("弓", "black")],
                     (5, 4): [("兵", "white"), ("侍", "white")]})
    valid2, _ = _moves(s2, 6, 4)
    assert (4, 4) not in valid2                 # 自分より高い駒は飛び越せない


def test_capture_keeps_own_piece_under_enemy():
    # 1段目自駒・2段目敵駒のマスを取る → 自駒は残り、その上に攻撃駒が乗る
    s = make_state({(5, 4): [("兵", "black"), ("槍", "black")],
                    (4, 4): [("侍", "black"), ("兵", "white")],
                    (8, 0): [("帥", "black")], (0, 8): [("帥", "white")]})
    ok, err = apply_move(s, 5, 4, 4, 4, "capture")
    assert ok, err
    assert stack_at(s, 4, 4) == [("侍", "black"), ("槍", "black")]
    assert stack_at(s, 5, 4) == [("兵", "black")]


def test_capture_removes_all_enemy_pieces_of_stack():
    s = make_state({(5, 4): [("兵", "black"), ("槍", "black")],
                    (4, 4): [("兵", "white"), ("侍", "white")],
                    (8, 0): [("帥", "black")], (0, 8): [("帥", "white")]})
    ok, err = apply_move(s, 5, 4, 4, 4, "capture")
    assert ok, err
    assert stack_at(s, 4, 4) == [("槍", "black")]


def test_tsuke_enemy_keeps_enemy_below():
    s = make_state({(5, 4): [("兵", "black")], (4, 4): [("侍", "white")],
                    (8, 0): [("帥", "black")], (0, 8): [("帥", "white")]})
    ok, err = apply_move(s, 5, 4, 4, 4, "tsuke_enemy")
    assert ok, err
    assert stack_at(s, 4, 4) == [("侍", "white"), ("兵", "black")]
    assert s.current_player == "white"


def test_cannot_move_enemy_piece_or_out_of_turn():
    s = create_initial_state("nyumon")
    ok, _ = apply_move(s, 2, 0, 3, 0)   # 黒番に白駒
    assert not ok
    ok, _ = apply_move(s, 6, 0, 3, 0)   # 不正な移動先
    assert not ok


# ── A3: 新（手駒を打つ） ─────────────────────────────────────────────────────

def test_arata_positions_initial_nyumon():
    s = create_initial_state("nyumon")
    pos = set(get_valid_arata_positions(s.board, "black", s.rules.max_stack))
    expected = {(r, c) for r in (6, 7, 8) for c in range(9)} - {(8, 4)}  # 帥の上は不可
    assert pos == expected
    wpos = set(get_valid_arata_positions(s.board, "white", s.rules.max_stack))
    assert wpos == {(r, c) for r in (0, 1, 2) for c in range(9)} - {(0, 4)}


def test_arata_frontline_ignores_buried_pieces():
    # 黒の最前線(3,4)の駒は白にツケられている → 最前列の計算に含めない
    s = make_state({(3, 4): [("兵", "black"), ("兵", "white")],
                    (6, 0): [("兵", "black")],
                    (8, 4): [("帥", "black")], (0, 4): [("帥", "white")]},
                   hand={"black": ["小"]})
    pos = set(get_valid_arata_positions(s.board, "black", s.rules.max_stack))
    assert min(r for r, _ in pos) == 6


def test_arata_apply_and_reject():
    s = create_initial_state("nyumon")
    ok, err = apply_arata(s, "小", 7, 0)
    assert ok, err
    assert stack_at(s, 7, 0) == [("小", "black")]
    assert len(s.hand_pieces["black"]) == 6
    assert s.current_player == "white"
    ok, _ = apply_arata(s, "小", 6, 0)   # 白の最前列(2)より前には打てない
    assert not ok
    ok, _ = apply_arata(s, "謀", 1, 0)   # 持っていない駒
    assert not ok


# ── A7: 勝敗・千日手 ─────────────────────────────────────────────────────────

def test_capture_sui_ends_game():
    s = make_state({(5, 4): [("兵", "black")], (4, 4): [("帥", "white")],
                    (8, 0): [("帥", "black")]})
    ok, err = apply_move(s, 5, 4, 4, 4)
    assert ok, err
    assert s.game_over and s.winner == "black"
    ok, _ = apply_move(s, 8, 0, 7, 0)
    assert not ok   # 終局後は指せない


def test_sennichite_draw_after_fourth_repetition():
    s = create_initial_state("nyumon")
    cycle = [(6, 0, 5, 0), (2, 0, 3, 0), (5, 0, 6, 0), (3, 0, 2, 0)]
    plies = 0
    while not s.game_over:
        fr, fc, tr, tc = cycle[plies % 4]
        ok, err = apply_move(s, fr, fc, tr, tc)
        assert ok, err
        plies += 1
        assert plies <= 12
    assert plies == 12 and s.winner is None
