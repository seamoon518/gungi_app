"""テスト用ヘルパー: 任意の盤面から GameState を組み立てる。"""

from typing import Dict, List, Optional, Tuple

from models.game_state import GameState, RULES_BY_LEVEL
from models.piece import Piece, PieceType
from logic.zobrist import HASHER

Cells = Dict[Tuple[int, int], List[Tuple[str, str]]]


def piece(t: str, owner: str) -> Piece:
    return Piece(PieceType(t), owner)


def make_state(
    cells: Cells,
    level: str = "joukyuu",
    current: str = "black",
    hand: Optional[Dict[str, List[str]]] = None,
    mode: str = "pvp",
    ai_player: Optional[str] = None,
) -> GameState:
    """cells: {(row, col): [(駒種, owner), ...下から順]}"""
    board = [[[] for _ in range(9)] for _ in range(9)]
    for (r, c), stack in cells.items():
        for t, o in stack:
            board[r][c].append(piece(t, o))
    hand_pieces = {"black": [], "white": []}
    for owner, types in (hand or {}).items():
        hand_pieces[owner] = [piece(t, owner) for t in types]
    state = GameState(
        board=board,
        current_player=current,
        hand_pieces=hand_pieces,
        level=level,
        mode=mode,
        phase="play",
        setup_done={"black": True, "white": True},
        rules=RULES_BY_LEVEL[level],
    )
    state.ai_player = ai_player
    state.position_history.append(HASHER.hash_state(state))
    return state


def stack_at(state: GameState, r: int, c: int) -> List[Tuple[str, str]]:
    return [(p.type.value, p.owner) for p in state.board[r][c]]


def count_pieces(state: GameState, owner: str) -> int:
    return sum(1 for row in state.board for st in row for p in st if p.owner == owner)
