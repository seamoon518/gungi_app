from pydantic import BaseModel
from typing import Literal, Optional


class NewGameRequest(BaseModel):
    level: Literal["nyumon", "shokyuu", "chukyuu", "joukyuu"] = "nyumon"
    mode: Literal["pvp", "ai"] = "pvp"
    ai_difficulty: Optional[Literal["easy", "normal", "hard"]] = None


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
