"""
Zobrist hashing for Gungi game states.

64bit 整数ハッシュを XOR で合成し、置換表キーと千日手検出に使用する。
文字列ハッシュより大幅に高速。
"""

import random
from typing import TYPE_CHECKING

from models.piece import PieceType

if TYPE_CHECKING:
    from models.game_state import GameState

# ── 定数 ─────────────────────────────────────────────────────────────────────

_PIECE_TYPES = list(PieceType)
_PT_INDEX = {pt: i for i, pt in enumerate(_PIECE_TYPES)}
_OWNER_INDEX = {"black": 0, "white": 1}
_ROWS = 9
_COLS = 9
_MAX_STACK = 3
_MAX_HAND = 10   # 1 種の駒種を手駒に持てる最大数（余裕をもって 10）


class ZobristHasher:
    """
    軍議の局面を 64bit 整数にハッシュする。

    テーブル構成:
      board_table[r][c][layer][piece_type_idx][owner_idx]  6,804 個
      hand_table[piece_type_idx][owner_idx][count]          280 個
      turn_table                                              1 個
    """

    def __init__(self, seed: int = 0x9E3779B97F4A7C15):
        rng = random.Random(seed)

        n_pt = len(_PIECE_TYPES)
        n_ow = 2

        # board_table[r][c][layer][pt][owner]
        self.board_table: list = [
            [
                [
                    [
                        [rng.getrandbits(64) for _ in range(n_ow)]
                        for _ in range(n_pt)
                    ]
                    for _ in range(_MAX_STACK)
                ]
                for _ in range(_COLS)
            ]
            for _ in range(_ROWS)
        ]

        # hand_table[pt][owner][count=0..MAX_HAND]
        # count=0 は XOR しない（0 との XOR は変化なし）ので 0 固定
        self.hand_table: list = [
            [
                [0] + [rng.getrandbits(64) for _ in range(_MAX_HAND)]
                for _ in range(n_ow)
            ]
            for _ in range(n_pt)
        ]

        # 手番: 黒番のときにこの値を XOR する
        self.turn_table: int = rng.getrandbits(64)

    def hash_state(self, state: "GameState") -> int:
        """局面全体を 64bit ハッシュ値にして返す。"""
        h = 0

        # 盤面上の駒
        for r in range(_ROWS):
            for c in range(_COLS):
                stack = state.board[r][c]
                for layer, piece in enumerate(stack):
                    if layer >= _MAX_STACK:
                        break
                    pt_i = _PT_INDEX[piece.type]
                    ow_i = _OWNER_INDEX[piece.owner]
                    h ^= self.board_table[r][c][layer][pt_i][ow_i]

        # 手駒（駒種ごとの枚数）
        for ow_str, ow_i in _OWNER_INDEX.items():
            hand = state.hand_pieces.get(ow_str, [])
            counts: dict = {}
            for p in hand:
                counts[p.type] = counts.get(p.type, 0) + 1
            for pt, cnt in counts.items():
                pt_i = _PT_INDEX[pt]
                cnt = min(cnt, _MAX_HAND)
                h ^= self.hand_table[pt_i][ow_i][cnt]

        # 手番
        if state.current_player == "black":
            h ^= self.turn_table

        return h


# モジュール共有シングルトン（固定シードで再現性を保証）
HASHER = ZobristHasher()
