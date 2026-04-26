"""
Arata (新): placing hand pieces onto the board.

Placement rules:
  - Valid squares are at or BEHIND the frontmost own top-piece row
    (for black: row >= frontmost_row; for white: row <= frontmost_row)
  - Only TOP pieces count toward frontmost calculation (buried pieces excluded)
  - Can place on empty squares
  - Can tsuke onto own-top squares where stack height < 3 and top piece is not 帅
    (arata tsuke is not restricted by the hand-piece "height 1" rule)
  - Cannot place on enemy-top squares
"""

from typing import List, Tuple
from models.piece import Piece, PieceType

Board = List[List[List[Piece]]]


def get_valid_arata_positions(board: Board, player: str, max_stack: int = 3) -> List[Tuple[int, int]]:
    """Return all (row, col) squares valid for arata placement."""
    # Find frontmost own top-piece row
    frontmost_row: int | None = None
    for r in range(9):
        for c in range(9):
            stack = board[r][c]
            if stack and stack[-1].owner == player:
                if player == "black":
                    if frontmost_row is None or r < frontmost_row:
                        frontmost_row = r
                else:
                    if frontmost_row is None or r > frontmost_row:
                        frontmost_row = r

    if frontmost_row is None:
        return []

    valid: List[Tuple[int, int]] = []
    for r in range(9):
        # black: valid rows are at or behind frontmost (r >= frontmost_row)
        # white: valid rows are at or behind frontmost (r <= frontmost_row)
        if player == "black" and r < frontmost_row:
            continue
        if player == "white" and r > frontmost_row:
            continue

        for c in range(9):
            stack = board[r][c]
            if not stack:
                valid.append((r, c))
            elif stack[-1].owner == player:
                # Tsuke with arata: allow up to max height (3)
                # Top must not be 帅
                if len(stack) < max_stack and stack[-1].type != PieceType.SUI:
                    valid.append((r, c))
            # enemy-top: skip
    return valid
