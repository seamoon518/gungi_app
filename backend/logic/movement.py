"""
Valid move calculation for Gungi pieces.

Rules implemented:
- Coordinate transform: +y = forward per player (black: row--, white: row++)
- Path blocking: pieces can't jump over others (except 砲/筒/弓 with height conditions)
- Tsuke (stack): allowed when destination stack height <= moving piece's height AND dest < max_stack
- Tsuke onto OWN piece: always allowed (subject to height rules), unless top is 帥
- Tsuke onto ENEMY piece: allowed (subject to same height rules), unless top is 帅
- Capture: allowed when top piece is enemy AND dest stack <= moving piece's height
- 帅 CANNOT be tsuke'd onto (absolute rule for both own and enemy)
- 帅 can tsuke onto other pieces only when sui_can_tsuke=True (師ツケあり)
- Max stack height: controlled by max_stack parameter (2 for 入門/初級/中級, 3 for 上級)

Returns MoveOptions(valid_moves, enemy_tsuke_moves):
  valid_moves      - all valid destination squares
  enemy_tsuke_moves - enemy squares where TSUKE (not capture) is also an option
"""

from math import gcd
from typing import List, Tuple, NamedTuple

from models.piece import Piece, PieceType
from logic.piece_moves import (
    FIXED_MOVES, JUMP_MOVES, NORMAL_MOVES,
    TAI_SLIDE_DIRS, CHU_SLIDE_DIRS, JUMP_PIECES,
)

Board = List[List[List[Piece]]]


class MoveOptions(NamedTuple):
    valid_moves: List[Tuple[int, int]]
    enemy_tsuke_moves: List[Tuple[int, int]]


def _in_bounds(row: int, col: int) -> bool:
    return 0 <= row < 9 and 0 <= col < 9


def _get_intermediate_squares(
    from_row: int, from_col: int, to_row: int, to_col: int
) -> List[Tuple[int, int]]:
    dr = to_row - from_row
    dc = to_col - from_col
    if dr == 0 and dc == 0:
        return []
    steps = gcd(abs(dr), abs(dc))
    if steps <= 1:
        return []
    step_r = dr // steps
    step_c = dc // steps
    return [
        (from_row + i * step_r, from_col + i * step_c)
        for i in range(1, steps)
    ]


def _can_tsuke(board: Board, src_height: int, dst_row: int, dst_col: int, max_stack: int = 3) -> bool:
    """Common tsuke conditions (ownership checked by caller)."""
    dst_stack = board[dst_row][dst_col]
    if not dst_stack:
        return False
    if len(dst_stack) >= max_stack:
        return False
    if len(dst_stack) > src_height:
        return False
    if dst_stack[-1].type == PieceType.SUI:
        return False  # 帅 cannot be tsuke'd onto (absolute rule)
    return True


def _can_capture(
    board: Board, src_height: int, dst_row: int, dst_col: int, attacker: str
) -> bool:
    dst_stack = board[dst_row][dst_col]
    if not dst_stack:
        return False
    if dst_stack[-1].owner == attacker:
        return False
    if len(dst_stack) > src_height:
        return False
    return True


def _path_clear_normal(board: Board, path: List[Tuple[int, int]]) -> bool:
    return all(not board[r][c] for r, c in path)


def _path_clear_jump(
    board: Board, path: List[Tuple[int, int]], src_height: int
) -> bool:
    return all(
        not board[r][c] or len(board[r][c]) <= src_height
        for r, c in path
    )


def _transform(
    src_row: int, src_col: int, dx: int, dy: int, row_mult: int
) -> Tuple[int, int]:
    return src_row + row_mult * dy, src_col + dx


def get_valid_moves(
    board: Board, row: int, col: int,
    max_stack: int = 3, sui_can_tsuke: bool = True
) -> MoveOptions:
    """
    Return MoveOptions with all valid destinations and enemy-tsuke-eligible squares.

    max_stack: maximum stack height allowed (2 for 入門/初級/中級, 3 for 上級)
    sui_can_tsuke: if False, 帅 cannot be placed on top of other pieces (師ツケなし)
    """
    stack = board[row][col]
    if not stack:
        return MoveOptions([], [])

    top = stack[-1]
    player = top.owner
    piece_type = top.type
    src_height = len(stack)

    row_mult = -1 if player == "black" else 1

    # When sui_can_tsuke=False and the moving piece is SUI,
    # SUI can only move to empty squares (no tsuke in any form).
    is_sui_no_tsuke = (piece_type == PieceType.SUI and not sui_can_tsuke)

    valid: List[Tuple[int, int]] = []
    enemy_tsuke: List[Tuple[int, int]] = []

    def _try_add(dst_row: int, dst_col: int, path: list, is_jump: bool = False) -> None:
        if not _in_bounds(dst_row, dst_col):
            return
        if is_jump:
            if not _path_clear_jump(board, path, src_height):
                return
        else:
            if not _path_clear_normal(board, path):
                return

        dst_stack = board[dst_row][dst_col]

        if not dst_stack:
            valid.append((dst_row, dst_col))

        elif dst_stack[-1].owner == player:
            # 自駒へのツケ（師ツケなしの場合はSUIのツケを禁止）
            if not is_sui_no_tsuke and _can_tsuke(board, src_height, dst_row, dst_col, max_stack):
                valid.append((dst_row, dst_col))

        else:
            # 敵駒：取ることは常に可能、ツケは師ツケなしの場合SUIは禁止
            can_cap = _can_capture(board, src_height, dst_row, dst_col, player)
            can_tsuke_e = (not is_sui_no_tsuke) and _can_tsuke(board, src_height, dst_row, dst_col, max_stack)

            if can_cap or can_tsuke_e:
                valid.append((dst_row, dst_col))
            if can_tsuke_e:
                enemy_tsuke.append((dst_row, dst_col))

    # --- 大（TAI）: unlimited cross sliding + fixed diagonals ---
    if piece_type == PieceType.TAI:
        for dr, dc in TAI_SLIDE_DIRS:
            r, c = row + dr, col + dc
            while _in_bounds(r, c):
                dst_stack = board[r][c]
                if not dst_stack:
                    valid.append((r, c))
                elif dst_stack[-1].owner == player:
                    if not is_sui_no_tsuke and _can_tsuke(board, src_height, r, c, max_stack):
                        valid.append((r, c))
                    break
                else:
                    can_cap = _can_capture(board, src_height, r, c, player)
                    can_tsuke_e = (not is_sui_no_tsuke) and _can_tsuke(board, src_height, r, c, max_stack)
                    if can_cap or can_tsuke_e:
                        valid.append((r, c))
                    if can_tsuke_e:
                        enemy_tsuke.append((r, c))
                    break
                r, c = r + dr, c + dc

        for dx, dy in FIXED_MOVES[PieceType.TAI][src_height]:
            dst_row, dst_col = _transform(row, col, dx, dy, row_mult)
            path = _get_intermediate_squares(row, col, dst_row, dst_col)
            _try_add(dst_row, dst_col, path)

    # --- 中（CHU）: unlimited diagonal sliding + fixed cross ---
    elif piece_type == PieceType.CHU:
        for dr, dc in CHU_SLIDE_DIRS:
            r, c = row + dr, col + dc
            while _in_bounds(r, c):
                dst_stack = board[r][c]
                if not dst_stack:
                    valid.append((r, c))
                elif dst_stack[-1].owner == player:
                    if not is_sui_no_tsuke and _can_tsuke(board, src_height, r, c, max_stack):
                        valid.append((r, c))
                    break
                else:
                    can_cap = _can_capture(board, src_height, r, c, player)
                    can_tsuke_e = (not is_sui_no_tsuke) and _can_tsuke(board, src_height, r, c, max_stack)
                    if can_cap or can_tsuke_e:
                        valid.append((r, c))
                    if can_tsuke_e:
                        enemy_tsuke.append((r, c))
                    break
                r, c = r + dr, c + dc

        for dx, dy in FIXED_MOVES[PieceType.CHU][src_height]:
            dst_row, dst_col = _transform(row, col, dx, dy, row_mult)
            path = _get_intermediate_squares(row, col, dst_row, dst_col)
            _try_add(dst_row, dst_col, path)

    # --- 弓/筒/砲: jump + normal moves ---
    elif piece_type in JUMP_PIECES:
        for dx, dy in JUMP_MOVES[piece_type][src_height]:
            dst_row, dst_col = _transform(row, col, dx, dy, row_mult)
            path = _get_intermediate_squares(row, col, dst_row, dst_col)
            _try_add(dst_row, dst_col, path, is_jump=True)

        for dx, dy in NORMAL_MOVES[piece_type][src_height]:
            dst_row, dst_col = _transform(row, col, dx, dy, row_mult)
            path = _get_intermediate_squares(row, col, dst_row, dst_col)
            _try_add(dst_row, dst_col, path, is_jump=False)

    # --- All other pieces (including 帅): fixed moves, normal path blocking ---
    else:
        for dx, dy in FIXED_MOVES.get(piece_type, {}).get(src_height, []):
            dst_row, dst_col = _transform(row, col, dx, dy, row_mult)
            path = _get_intermediate_squares(row, col, dst_row, dst_col)
            _try_add(dst_row, dst_col, path)

    return MoveOptions(valid_moves=valid, enemy_tsuke_moves=enemy_tsuke)
