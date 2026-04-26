"""
Setup phase logic for 中級/上級 initial placement.

Rules:
- Each player places pieces into their own territory (3 rows from back rank)
- First piece placed MUST be 帅 (SUI)
- Can tsuke onto own pieces (not onto SUI), subject to max_stack
- Cannot place on enemy-top squares or outside own territory
- Either player may declare "済" (done) on their turn
- When 後手 (white) declares 済, game starts regardless of 先手 (black)
- When 先手 (black) declares 済, only white continues until white declares 済
"""

from typing import List, Tuple
from models.piece import Piece, PieceType

Board = List[List[List[Piece]]]

_SETUP_ROW_RANGES = {
    "black": range(6, 9),
    "white": range(0, 3),
}


def get_valid_setup_positions(board: Board, player: str, max_stack: int) -> List[Tuple[int, int]]:
    """Return all valid positions where the current player can place a piece during setup."""
    valid_rows = _SETUP_ROW_RANGES[player]
    valid: List[Tuple[int, int]] = []
    for r in valid_rows:
        for c in range(9):
            stack = board[r][c]
            if not stack:
                valid.append((r, c))
            elif stack[-1].owner == player:
                # Can tsuke onto own piece if under max_stack and top is not SUI
                if len(stack) < max_stack and stack[-1].type != PieceType.SUI:
                    valid.append((r, c))
            # enemy-top or SUI-top: skip
    return valid


def has_placed_sui(board: Board, player: str) -> bool:
    """Check if the player has placed their SUI on the board."""
    for r in _SETUP_ROW_RANGES[player]:
        for c in range(9):
            for piece in board[r][c]:
                if piece.type == PieceType.SUI and piece.owner == player:
                    return True
    return False
