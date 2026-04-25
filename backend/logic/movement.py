"""
Valid move calculation for Gungi pieces.

Rules implemented:
- Coordinate transform: +y = forward per player (black: row--, white: row++)
- Path blocking: pieces can't jump over others (except 砲/筒/弓 with height conditions)
- Tsuke (stack): allowed when destination stack height <= moving piece's height AND dest < 3
- Tsuke onto OWN piece: always allowed (subject to height rules), unless top is 帥
- Tsuke onto ENEMY piece: allowed (subject to same height rules), unless top is 帅
- Capture: allowed when top piece is enemy AND dest stack <= moving piece's height
- 帅 CANNOT be tsuke'd onto (absolute rule for both own and enemy)
- 帅 CAN tsuke onto other pieces (no special restriction)
- Max stack height: 3

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


def _can_tsuke(board: Board, src_height: int, dst_row: int, dst_col: int) -> bool:
    """Common tsuke conditions (ownership checked by caller)."""
    dst_stack = board[dst_row][dst_col]
    if not dst_stack:
        return False
    if len(dst_stack) >= 3:
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


def get_valid_moves(board: Board, row: int, col: int) -> MoveOptions:
    """
    Return MoveOptions with all valid destinations and enemy-tsuke-eligible squares.
    """
    stack = board[row][col]
    if not stack:
        return MoveOptions([], [])

    top = stack[-1]
    player = top.owner
    piece_type = top.type
    src_height = len(stack)

    row_mult = -1 if player == "black" else 1

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
            # Own piece: tsuke (帅 CAN tsuke now, only restrict destination being 帅)
            if _can_tsuke(board, src_height, dst_row, dst_col):
                valid.append((dst_row, dst_col))

        else:
            # Enemy piece: capture possible?
            can_cap = _can_capture(board, src_height, dst_row, dst_col, player)
            # Enemy tsuke possible? (same height rules, top must not be 帅)
            can_tsuke_e = _can_tsuke(board, src_height, dst_row, dst_col)

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
                    if _can_tsuke(board, src_height, r, c):
                        valid.append((r, c))
                    break
                else:
                    can_cap = _can_capture(board, src_height, r, c, player)
                    can_tsuke_e = _can_tsuke(board, src_height, r, c)
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
                    if _can_tsuke(board, src_height, r, c):
                        valid.append((r, c))
                    break
                else:
                    can_cap = _can_capture(board, src_height, r, c, player)
                    can_tsuke_e = _can_tsuke(board, src_height, r, c)
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

    # --- All other pieces: fixed moves, normal path blocking ---
    else:
        for dx, dy in FIXED_MOVES.get(piece_type, {}).get(src_height, []):
            dst_row, dst_col = _transform(row, col, dx, dy, row_mult)
            path = _get_intermediate_squares(row, col, dst_row, dst_col)
            _try_add(dst_row, dst_col, path)

    return MoveOptions(valid_moves=valid, enemy_tsuke_moves=enemy_tsuke)
