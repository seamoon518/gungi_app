from enum import Enum
from dataclasses import dataclass
from typing import Literal


class PieceType(str, Enum):
    SUI = "帥"
    TAI = "大"
    CHU = "中"
    SHO = "小"
    SAM = "侍"
    YAR = "槍"
    KIB = "馬"
    SHI = "忍"
    TOR = "砦"
    HYO = "兵"
    OZU = "砲"
    TSU = "筒"
    YUM = "弓"
    BOU = "謀"


@dataclass
class Piece:
    type: PieceType
    owner: Literal["black", "white"]

    def to_dict(self) -> dict:
        return {"type": self.type.value, "owner": self.owner}
