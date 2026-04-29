from typing import List, Optional, Literal, Dict
from dataclasses import dataclass, field
from models.piece import Piece


@dataclass(frozen=True)
class GameRules:
    max_stack: int = 3
    sui_can_tsuke: bool = True  # 師ツケ: 帅が他の駒の上に乗れるか


RULES_BY_LEVEL: Dict[str, GameRules] = {
    "nyumon":  GameRules(max_stack=2, sui_can_tsuke=False),
    "shokyuu": GameRules(max_stack=2, sui_can_tsuke=False),
    "chukyuu": GameRules(max_stack=2, sui_can_tsuke=True),
    "joukyuu": GameRules(max_stack=3, sui_can_tsuke=True),
}


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
    level: str = "nyumon"
    mode: str = "pvp"
    ai_difficulty: Optional[str] = None
    ai_player: Optional[Literal["black", "white"]] = None  # AI が担当するプレイヤー
    # "setup": 中級/上級の初期配置フェーズ, "play": 通常ゲーム
    phase: Literal["setup", "play"] = "play"
    setup_done: Dict[str, bool] = field(
        default_factory=lambda: {"black": False, "white": False}
    )
    rules: GameRules = field(default_factory=GameRules)

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
            "level": self.level,
            "mode": self.mode,
            "phase": self.phase,
            "setup_done": dict(self.setup_done),
            "ai_player": self.ai_player,
            "last_move": (
                {
                    "from_row": self.move_history[-1].from_row,
                    "from_col": self.move_history[-1].from_col,
                    "to_row":   self.move_history[-1].to_row,
                    "to_col":   self.move_history[-1].to_col,
                }
                if self.move_history else None
            ),
        }
