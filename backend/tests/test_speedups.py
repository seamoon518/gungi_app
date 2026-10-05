"""高速化の前後で結果が変わらないことの確認（合法手生成・評価関数）"""

import random

import pytest

from models.piece import Piece, PieceType
from logic.movement import get_valid_moves
from tests import _movement_reference as ref

TYPES = list(PieceType)


def _random_board(rng: random.Random):
    board = [[[] for _ in range(9)] for _ in range(9)]
    for _ in range(rng.randint(5, 40)):
        r, c = rng.randrange(9), rng.randrange(9)
        if len(board[r][c]) < 3:
            board[r][c].append(Piece(rng.choice(TYPES), rng.choice(["black", "white"])))
    return board


@pytest.mark.parametrize("seed", range(40))
def test_get_valid_moves_matches_reference(seed):
    rng = random.Random(seed)
    for _ in range(20):
        board = _random_board(rng)
        for max_stack, sui_tsuke in ((2, False), (2, True), (3, True)):
            for r in range(9):
                for c in range(9):
                    a = get_valid_moves(board, r, c, max_stack, sui_tsuke)
                    b = ref.get_valid_moves(board, r, c, max_stack, sui_tsuke)
                    assert a.valid_moves == b.valid_moves, (seed, r, c)
                    assert a.enemy_tsuke_moves == b.enemy_tsuke_moves, (seed, r, c)
