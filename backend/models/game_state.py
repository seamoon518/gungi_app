from typing import List, Optional, Literal, Dict
from dataclasses import dataclass, field
from models.piece import Piece


@dataclass
class Move:
    from_row: int
    from_col: int
    to_row: int
    to_col: int


@dataclass
class GameState:
    # board[row][col] = stack of Piece (index 0 = bottom, -1 = top)
    # row 0 = white back rank, row 8 = black back rank
    board: List[List[List[Piece]]]
    current_player: Literal["black", "white"]
    hand_pieces: Dict[str, List[Piece]] = field(
        default_factory=lambda: {"black": [], "white": []}
    )
    move_history: List[Move] = field(default_factory=list)
    position_history: List[str] = field(default_factory=list)
    game_over: bool = False
    winner: Optional[Literal["black", "white"]] = None

    def board_to_dict(self) -> list:
        result = []
        for row in self.board:
            row_data = []
            for stack in row:
                row_data.append({"stack": [p.to_dict() for p in stack]})
            result.append(row_data)
        return result

    def to_dict(self, game_id: str) -> dict:
        return {
            "game_id": game_id,
            "board": self.board_to_dict(),
            "current_player": self.current_player,
            "hand_pieces": {
                player: [p.to_dict() for p in pieces]
                for player, pieces in self.hand_pieces.items()
            },
            "game_over": self.game_over,
            "winner": self.winner,
            "move_count": len(self.move_history),
        }
