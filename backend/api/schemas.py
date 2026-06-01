from pydantic import BaseModel
from typing import Literal, Optional


class NewGameRequest(BaseModel):
    level: Literal["nyumon", "shokyuu", "chukyuu", "joukyuu"] = "nyumon"
    mode: Literal["pvp", "ai", "ai_vs_ai"] = "pvp"
    ai_difficulty: Optional[Literal["easy", "normal", "hard"]] = None       # AI vs Human
    ai_difficulty_black: Optional[Literal["easy", "normal", "hard"]] = None  # AI同士: 黒
    ai_difficulty_white: Optional[Literal["easy", "normal", "hard"]] = None  # AI同士: 白
    human_player: Optional[Literal["black", "white"]] = None                 # 人間が担当する陣（"black"=先手, "white"=後手）


class MoveRequest(BaseModel):
    from_row: int
    from_col: int
    to_row: int
    to_col: int
    action: Literal["auto", "capture", "tsuke_enemy"] = "auto"


class ValidMovesResponse(BaseModel):
    valid_moves: list[list[int]]
    enemy_tsuke_moves: list[list[int]]


class ArataRequest(BaseModel):
    piece_type: str   # e.g. "小", "槍"
    to_row: int
    to_col: int


class ValidArataResponse(BaseModel):
    valid_positions: list[list[int]]  # [[row, col], ...]


class SetupPlaceRequest(BaseModel):
    piece_type: str
    to_row: int
    to_col: int


class BoushouRequest(BaseModel):
    from_row: int
    from_col: int
    to_row: int
    to_col: int
    target_index: int  # ツケ前のdestスタック内の敵駒インデックス（0=最下段）
