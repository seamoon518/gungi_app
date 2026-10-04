from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional

# 盤面の座標（0〜8）。範囲外は 422 で弾く（負の値が Python の負インデックスとして
# 9 段目などに読み替えられ、駒がワープする不正操作を防ぐ）
Coord = Annotated[int, Field(ge=0, le=8)]


class NewGameRequest(BaseModel):
    level: Literal["nyumon", "shokyuu", "chukyuu", "joukyuu"] = "nyumon"
    mode: Literal["pvp", "ai", "ai_vs_ai"] = "pvp"
    ai_difficulty: Optional[Literal["easy", "normal", "hard"]] = None       # AI vs Human
    ai_difficulty_black: Optional[Literal["easy", "normal", "hard"]] = None  # AI同士: 黒
    ai_difficulty_white: Optional[Literal["easy", "normal", "hard"]] = None  # AI同士: 白
    human_player: Optional[Literal["black", "white"]] = None                 # 人間が担当する陣（"black"=先手, "white"=後手）


class MoveRequest(BaseModel):
    from_row: Coord
    from_col: Coord
    to_row: Coord
    to_col: Coord
    action: Literal["auto", "capture", "tsuke_enemy"] = "auto"


class ValidMovesResponse(BaseModel):
    valid_moves: list[list[int]]
    enemy_tsuke_moves: list[list[int]]


class ArataRequest(BaseModel):
    piece_type: str   # e.g. "小", "槍"
    to_row: Coord
    to_col: Coord


class ValidArataResponse(BaseModel):
    valid_positions: list[list[int]]  # [[row, col], ...]


class SetupPlaceRequest(BaseModel):
    piece_type: str
    to_row: Coord
    to_col: Coord


class BoushouRequest(BaseModel):
    from_row: Coord
    from_col: Coord
    to_row: Coord
    to_col: Coord
    target_index: Annotated[int, Field(ge=0, le=2)]  # ツケ前のdestスタック内の敵駒インデックス（0=最下段）
