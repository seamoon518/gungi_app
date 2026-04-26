"""
Game engine: creates initial game state, validates and applies moves / arata / setup.

Level initial placements:
  nyumon (入門編):
    Fixed placement, no special pieces (砲/筒/弓/謀 not used), max stack 2, no 師ツケ

  shokyuu (初級編):
    Fixed placement with 弓 added, max stack 2, no 師ツケ
    White board: 中(3,0) 帅(4,0) 大(5,0)
                 馬(1,1) 弓(2,1) 槍(4,1) 弓(7,1) 忍(8,1)
                 兵(0,2) 砦(2,2) 侍(3,2) 兵(4,2) 侍(5,2) 砦(6,2) 兵(8,2)
    Hand: 小×2, 槍×2, 忍×1, 馬×1, 兵×1

  chukyuu (中級編) / joukyuu (上級編):
    Custom setup phase; all 25 pieces per player start in hand
"""

import copy
from typing import List, Tuple, Optional

from models.piece import Piece, PieceType
from models.game_state import GameState, Move, GameRules, RULES_BY_LEVEL
from logic.movement import get_valid_moves
from logic.arata import get_valid_arata_positions
from logic.setup import get_valid_setup_positions, has_placed_sui
from logic.rules import (
    apply_capture, apply_tsuke, apply_plain_move,
    get_winner, board_hash, check_sennichite,
)

Board = List[List[List[Piece]]]

# ── 入門編 (nyumon) layout ─────────────────────────────────────────────────────
_NYUMON_WHITE_LAYOUT = [
    (3, 0, PieceType.CHU), (4, 0, PieceType.SUI), (5, 0, PieceType.TAI),
    (1, 1, PieceType.SHI), (4, 1, PieceType.YAR), (7, 1, PieceType.SHI),
    (0, 2, PieceType.HYO), (2, 2, PieceType.TOR), (3, 2, PieceType.SAM),
    (4, 2, PieceType.HYO), (5, 2, PieceType.SAM), (6, 2, PieceType.TOR),
    (8, 2, PieceType.HYO),
]
_NYUMON_BLACK_LAYOUT = [
    (0, 6, PieceType.HYO), (2, 6, PieceType.TOR), (3, 6, PieceType.SAM),
    (4, 6, PieceType.HYO), (5, 6, PieceType.SAM), (6, 6, PieceType.TOR),
    (8, 6, PieceType.HYO),
    (1, 7, PieceType.SHI), (4, 7, PieceType.YAR), (7, 7, PieceType.SHI),
    (3, 8, PieceType.TAI), (4, 8, PieceType.SUI), (5, 8, PieceType.CHU),
]
_NYUMON_HAND_TYPES = [
    PieceType.SHO, PieceType.SHO,
    PieceType.YAR, PieceType.YAR,
    PieceType.KIB, PieceType.KIB,
    PieceType.HYO,
]

# ── 初級編 (shokyuu) layout ────────────────────────────────────────────────────
_SHOKYUU_WHITE_LAYOUT = [
    (3, 0, PieceType.CHU), (4, 0, PieceType.SUI), (5, 0, PieceType.TAI),
    (1, 1, PieceType.KIB), (2, 1, PieceType.YUM), (4, 1, PieceType.YAR),
    (7, 1, PieceType.YUM), (8, 1, PieceType.SHI),
    (0, 2, PieceType.HYO), (2, 2, PieceType.TOR), (3, 2, PieceType.SAM),
    (4, 2, PieceType.HYO), (5, 2, PieceType.SAM), (6, 2, PieceType.TOR),
    (8, 2, PieceType.HYO),
]
_SHOKYUU_BLACK_LAYOUT = [
    (0, 6, PieceType.HYO), (2, 6, PieceType.TOR), (3, 6, PieceType.SAM),
    (4, 6, PieceType.HYO), (5, 6, PieceType.SAM), (6, 6, PieceType.TOR),
    (8, 6, PieceType.HYO),
    (1, 7, PieceType.KIB), (2, 7, PieceType.YUM), (4, 7, PieceType.YAR),
    (7, 7, PieceType.YUM), (8, 7, PieceType.SHI),
    (3, 8, PieceType.TAI), (4, 8, PieceType.SUI), (5, 8, PieceType.CHU),
]
_SHOKYUU_HAND_TYPES = [
    PieceType.SHO, PieceType.SHO,
    PieceType.YAR, PieceType.YAR,
    PieceType.SHI,
    PieceType.KIB,
    PieceType.HYO,
]

# ── 中級/上級: all 25 pieces start in hand ─────────────────────────────────────
_ALL_PIECE_TYPES = [
    PieceType.SUI,
    PieceType.TAI,
    PieceType.CHU,
    PieceType.SHO, PieceType.SHO,
    PieceType.SAM, PieceType.SAM,
    PieceType.YAR, PieceType.YAR, PieceType.YAR,
    PieceType.KIB, PieceType.KIB,
    PieceType.SHI, PieceType.SHI,
    PieceType.TOR, PieceType.TOR,
    PieceType.HYO, PieceType.HYO, PieceType.HYO, PieceType.HYO,
    PieceType.OZU,
    PieceType.TSU,
    PieceType.YUM, PieceType.YUM,
    PieceType.BOU,
]


def _make_empty_board() -> Board:
    return [[[] for _ in range(9)] for _ in range(9)]


def _create_fixed_state(
    level: str, mode: str, ai_difficulty: Optional[str],
    rules: GameRules,
    white_layout: list, black_layout: list, hand_types: list,
) -> GameState:
    board = _make_empty_board()
    for col, row, pt in white_layout:
        board[row][col].append(Piece(pt, "white"))
    for col, row, pt in black_layout:
        board[row][col].append(Piece(pt, "black"))

    hand_pieces = {
        "black": [Piece(pt, "black") for pt in hand_types],
        "white": [Piece(pt, "white") for pt in hand_types],
    }
    state = GameState(
        board=board,
        current_player="black",
        hand_pieces=hand_pieces,
        level=level,
        mode=mode,
        ai_difficulty=ai_difficulty,
        phase="play",
        setup_done={"black": True, "white": True},
        rules=rules,
    )
    state.position_history.append(board_hash(board))
    return state


def _create_setup_state(
    level: str, mode: str, ai_difficulty: Optional[str],
    rules: GameRules,
) -> GameState:
    board = _make_empty_board()
    hand_pieces = {
        "black": [Piece(pt, "black") for pt in _ALL_PIECE_TYPES],
        "white": [Piece(pt, "white") for pt in _ALL_PIECE_TYPES],
    }
    return GameState(
        board=board,
        current_player="black",
        hand_pieces=hand_pieces,
        level=level,
        mode=mode,
        ai_difficulty=ai_difficulty,
        phase="setup",
        setup_done={"black": False, "white": False},
        rules=rules,
    )


def create_initial_state(
    level: str = "nyumon",
    mode: str = "pvp",
    ai_difficulty: Optional[str] = None,
) -> GameState:
    rules = RULES_BY_LEVEL.get(level, GameRules())
    if level == "shokyuu":
        return _create_fixed_state(
            level, mode, ai_difficulty, rules,
            _SHOKYUU_WHITE_LAYOUT, _SHOKYUU_BLACK_LAYOUT, _SHOKYUU_HAND_TYPES,
        )
    elif level in ("chukyuu", "joukyuu"):
        return _create_setup_state(level, mode, ai_difficulty, rules)
    else:  # nyumon (default)
        return _create_fixed_state(
            level, mode, ai_difficulty, rules,
            _NYUMON_WHITE_LAYOUT, _NYUMON_BLACK_LAYOUT, _NYUMON_HAND_TYPES,
        )


def _is_enemy(board: Board, player: str, row: int, col: int) -> bool:
    dst = board[row][col]
    return bool(dst) and dst[-1].owner != player


def _is_own(board: Board, player: str, row: int, col: int) -> bool:
    dst = board[row][col]
    return bool(dst) and dst[-1].owner == player


def _finish_turn(state: GameState, player: str) -> Tuple[bool, str]:
    """Check win/sennichite and switch turn. Returns (success, error)."""
    winner = get_winner(state.board)
    if winner:
        state.game_over = True
        state.winner = winner
        return True, ""

    h = board_hash(state.board)
    state.position_history.append(h)
    if check_sennichite(state.position_history, h):
        state.game_over = True
        state.winner = None
        return True, ""

    state.current_player = "white" if player == "black" else "black"
    return True, ""


def apply_move(
    state: GameState,
    from_row: int, from_col: int,
    to_row: int, to_col: int,
    action: str = "auto",
) -> Tuple[bool, str]:
    if state.game_over:
        return False, "Game is already over."
    if state.phase != "play":
        return False, "初期配置フェーズ中は駒を動かせません。"

    src_stack = state.board[from_row][from_col]
    if not src_stack:
        return False, "No piece at source square."

    top_piece = src_stack[-1]
    if top_piece.owner != state.current_player:
        return False, "Not your piece."

    options = get_valid_moves(
        state.board, from_row, from_col,
        state.rules.max_stack, state.rules.sui_can_tsuke,
    )
    if (to_row, to_col) not in options.valid_moves:
        return False, "Invalid move."

    if action == "tsuke_enemy" and (to_row, to_col) not in options.enemy_tsuke_moves:
        return False, "Cannot tsuke that enemy square."

    new_board = copy.deepcopy(state.board)
    moving_piece = new_board[from_row][from_col][-1]
    player = state.current_player

    if action == "tsuke_enemy":
        apply_tsuke(new_board, moving_piece, from_row, from_col, to_row, to_col)
    elif _is_enemy(new_board, player, to_row, to_col):
        apply_capture(new_board, moving_piece, from_row, from_col, to_row, to_col)
    elif _is_own(new_board, player, to_row, to_col):
        apply_tsuke(new_board, moving_piece, from_row, from_col, to_row, to_col)
    else:
        apply_plain_move(new_board, moving_piece, from_row, from_col, to_row, to_col)

    state.board = new_board
    state.move_history.append(Move(from_row, from_col, to_row, to_col))
    return _finish_turn(state, player)


def apply_arata(
    state: GameState,
    piece_type_str: str,
    to_row: int,
    to_col: int,
) -> Tuple[bool, str]:
    """Place a hand piece onto the board (通常ゲームフェーズ)."""
    if state.game_over:
        return False, "Game is already over."
    if state.phase != "play":
        return False, "初期配置フェーズ中は新を使えません。"

    player = state.current_player

    try:
        piece_type = PieceType(piece_type_str)
    except ValueError:
        return False, f"Unknown piece type: {piece_type_str}"

    hand = state.hand_pieces[player]
    hand_idx = next((i for i, p in enumerate(hand) if p.type == piece_type), None)
    if hand_idx is None:
        return False, "Piece not in hand."

    valid = get_valid_arata_positions(state.board, player, state.rules.max_stack)
    if (to_row, to_col) not in valid:
        return False, "Invalid arata position."

    piece = hand.pop(hand_idx)

    new_board = copy.deepcopy(state.board)
    new_board[to_row][to_col].append(piece)
    state.board = new_board
    state.move_history.append(Move(-1, -1, to_row, to_col))
    return _finish_turn(state, player)


def apply_setup_place(
    state: GameState,
    piece_type_str: str,
    to_row: int,
    to_col: int,
) -> Tuple[bool, str]:
    """Place a piece during the setup phase (中級/上級)."""
    if state.phase != "setup":
        return False, "初期配置フェーズではありません。"

    player = state.current_player

    try:
        piece_type = PieceType(piece_type_str)
    except ValueError:
        return False, f"Unknown piece type: {piece_type_str}"

    # SUI must be placed before any other piece
    if not has_placed_sui(state.board, player) and piece_type != PieceType.SUI:
        return False, "帥を先に配置してください。"

    hand = state.hand_pieces[player]
    hand_idx = next((i for i, p in enumerate(hand) if p.type == piece_type), None)
    if hand_idx is None:
        return False, "Piece not in hand."

    valid = get_valid_setup_positions(state.board, player, state.rules.max_stack)
    if (to_row, to_col) not in valid:
        return False, "自陣（3列目まで）にのみ配置できます。"

    piece = hand.pop(hand_idx)
    new_board = copy.deepcopy(state.board)
    new_board[to_row][to_col].append(piece)
    state.board = new_board

    # After black declares 済, white keeps the turn
    if state.setup_done["black"]:
        state.current_player = "white"
    else:
        state.current_player = "white" if player == "black" else "black"

    return True, ""


def apply_setup_done(state: GameState) -> Tuple[bool, str]:
    """Declare 済 during setup phase."""
    if state.phase != "setup":
        return False, "初期配置フェーズではありません。"

    player = state.current_player

    if not has_placed_sui(state.board, player):
        return False, "帥を配置してから済を宣言してください。"

    state.setup_done[player] = True

    if player == "white":
        # 後手が済を宣言 → ゲーム開始（先手が済を宣言していなくても）
        state.phase = "play"
        state.current_player = "black"
        state.position_history.append(board_hash(state.board))
    else:
        # 先手が済を宣言 → 後手のみ続けて配置できる
        state.current_player = "white"

    return True, ""
