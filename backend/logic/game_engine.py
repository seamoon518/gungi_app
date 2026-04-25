"""
Game engine: creates initial game state (level 1), validates and applies moves / arata.

Level 1 initial placement (from 初期配置_level1.md):
  White board pieces:
    (3,0):中  (4,0):帅  (5,0):大
    (1,1):忍  (4,1):槍  (7,1):忍
    (0,2):兵  (2,2):砦  (3,2):侍  (4,2):兵  (5,2):侍  (6,2):砦  (8,2):兵

  Black board pieces:
    (0,6):兵  (2,6):砦  (3,6):侍  (4,6):兵  (5,6):侍  (6,6):砦  (8,6):兵
    (1,7):忍  (4,7):槍  (7,7):忍
    (3,8):大  (4,8):帅  (5,8):中

  Hand pieces (each player): 小×2, 槍×2, 馬×2, 兵×1
"""

import copy
from typing import List, Tuple, Optional

from models.piece import Piece, PieceType
from models.game_state import GameState, Move
from logic.movement import get_valid_moves
from logic.arata import get_valid_arata_positions
from logic.rules import (
    apply_capture, apply_tsuke, apply_plain_move,
    get_winner, board_hash, check_sennichite,
)

Board = List[List[List[Piece]]]

_WHITE_LAYOUT = [
    (3, 0, PieceType.CHU), (4, 0, PieceType.SUI), (5, 0, PieceType.TAI),
    (1, 1, PieceType.SHI), (4, 1, PieceType.YAR), (7, 1, PieceType.SHI),
    (0, 2, PieceType.HYO), (2, 2, PieceType.TOR), (3, 2, PieceType.SAM),
    (4, 2, PieceType.HYO), (5, 2, PieceType.SAM), (6, 2, PieceType.TOR),
    (8, 2, PieceType.HYO),
]

_BLACK_LAYOUT = [
    (0, 6, PieceType.HYO), (2, 6, PieceType.TOR), (3, 6, PieceType.SAM),
    (4, 6, PieceType.HYO), (5, 6, PieceType.SAM), (6, 6, PieceType.TOR),
    (8, 6, PieceType.HYO),
    (1, 7, PieceType.SHI), (4, 7, PieceType.YAR), (7, 7, PieceType.SHI),
    (3, 8, PieceType.TAI), (4, 8, PieceType.SUI), (5, 8, PieceType.CHU),
]

_HAND_TYPES = [
    PieceType.SHO, PieceType.SHO,
    PieceType.YAR, PieceType.YAR,
    PieceType.KIB, PieceType.KIB,
    PieceType.HYO,
]


def _make_empty_board() -> Board:
    return [[[] for _ in range(9)] for _ in range(9)]


def create_initial_state() -> GameState:
    board = _make_empty_board()
    for col, row, pt in _WHITE_LAYOUT:
        board[row][col].append(Piece(pt, "white"))
    for col, row, pt in _BLACK_LAYOUT:
        board[row][col].append(Piece(pt, "black"))

    hand_pieces = {
        "black": [Piece(pt, "black") for pt in _HAND_TYPES],
        "white": [Piece(pt, "white") for pt in _HAND_TYPES],
    }
    state = GameState(board=board, current_player="black", hand_pieces=hand_pieces)
    state.position_history.append(board_hash(board))
    return state


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

    src_stack = state.board[from_row][from_col]
    if not src_stack:
        return False, "No piece at source square."

    top_piece = src_stack[-1]
    if top_piece.owner != state.current_player:
        return False, "Not your piece."

    options = get_valid_moves(state.board, from_row, from_col)
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
    """Place a hand piece onto the board."""
    if state.game_over:
        return False, "Game is already over."

    player = state.current_player

    try:
        piece_type = PieceType(piece_type_str)
    except ValueError:
        return False, f"Unknown piece type: {piece_type_str}"

    hand = state.hand_pieces[player]
    hand_idx = next((i for i, p in enumerate(hand) if p.type == piece_type), None)
    if hand_idx is None:
        return False, "Piece not in hand."

    valid = get_valid_arata_positions(state.board, player)
    if (to_row, to_col) not in valid:
        return False, "Invalid arata position."

    # Remove from hand AFTER validation passes
    piece = hand.pop(hand_idx)

    new_board = copy.deepcopy(state.board)
    new_board[to_row][to_col].append(piece)
    state.board = new_board
    state.move_history.append(Move(-1, -1, to_row, to_col))
    return _finish_turn(state, player)
