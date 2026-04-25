"""
Game rule helpers for Gungi:
  - apply_capture: remove enemy pieces from target stack, handle mixed stacks
  - check_boushou: detect 謀 defection (寝返り) conditions
  - board_hash: produce a string hash of the board for 千日手 detection
"""

import json
from typing import List, Optional

from models.piece import Piece, PieceType

Board = List[List[List[Piece]]]


def apply_capture(
    board: Board, attacker: Piece, from_row: int, from_col: int,
    to_row: int, to_col: int
) -> None:
    """
    Execute a capture move in-place on the board.
    - Remove all enemy pieces from the top of the destination stack.
    - Own pieces at the bottom of the mixed stack are preserved.
    - Move the attacking piece on top of the remaining stack.
    """
    attacking_stack = board[from_row][from_col]
    dest_stack = board[to_row][to_col]

    # Remove the attacking piece from its current position
    attacking_stack.pop()

    # Strip enemy pieces from the top of the destination stack
    player = attacker.owner
    while dest_stack and dest_stack[-1].owner != player:
        dest_stack.pop()

    # Place attacker on top of the remaining stack
    dest_stack.append(attacker)


def apply_tsuke(
    board: Board, piece: Piece, from_row: int, from_col: int,
    to_row: int, to_col: int
) -> None:
    """
    Execute a tsuke (stack) move in-place on the board.
    """
    board[from_row][from_col].pop()
    board[to_row][to_col].append(piece)


def apply_plain_move(
    board: Board, piece: Piece, from_row: int, from_col: int,
    to_row: int, to_col: int
) -> None:
    """
    Execute a plain move to an empty square.
    """
    board[from_row][from_col].pop()
    board[to_row][to_col].append(piece)


def get_winner(board: Board) -> Optional[str]:
    """
    Check if either player's 帥 has been captured.
    Returns "black" or "white" if one side won, else None.
    """
    has_black_sui = False
    has_white_sui = False
    for row in board:
        for stack in row:
            for piece in stack:
                if piece.type == PieceType.SUI:
                    if piece.owner == "black":
                        has_black_sui = True
                    else:
                        has_white_sui = True

    if not has_black_sui:
        return "white"
    if not has_white_sui:
        return "black"
    return None


def board_hash(board: Board) -> str:
    """
    Produce a canonical string representation of the board for 千日手 detection.
    """
    rows = []
    for row in board:
        cells = []
        for stack in row:
            cell_str = ",".join(f"{p.type.value}{p.owner[0]}" for p in stack)
            cells.append(cell_str)
        rows.append("|".join(cells))
    return "/".join(rows)


def check_sennichite(position_history: List[str], current_hash: str) -> bool:
    """Return True if the current position has appeared 4 times (千日手)."""
    return position_history.count(current_hash) >= 3


def check_boushou_defection(
    board: Board, piece: Piece, to_row: int, to_col: int, hand_pieces: List
) -> Optional[PieceType]:
    """
    Check if 謀 defection (寝返り) can be triggered after tsuke-ing onto an enemy.
    Returns the enemy PieceType to defect, or None if not applicable.
    MVP: hand_pieces is always empty, so always returns None.
    """
    if piece.type != PieceType.BOU:
        return None
    dest_stack = board[to_row][to_col]
    if not dest_stack:
        return None
    # The piece just moved is now on top; below it is the enemy piece we tsuked onto
    if len(dest_stack) < 2:
        return None
    enemy_piece = dest_stack[-2]
    if enemy_piece.owner == piece.owner:
        return None
    # Check if player has matching hand piece
    enemy_type = enemy_piece.type
    if any(p.type == enemy_type for p in hand_pieces):
        return enemy_type
    return None
