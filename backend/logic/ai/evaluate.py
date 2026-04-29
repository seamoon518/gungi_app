"""
Phase C 評価関数: 駒得 + 位置評価 + 帅安全度 + スタック価値

Phase B から Phase C への強化ポイント:
  1. 位置評価: 中央制御・前進ボーナス
  2. 帅安全度: 近くに敵がいるとペナルティ
  3. スタック価値: 高段の駒にボーナス
"""

from typing import Dict
from models.piece import PieceType
from models.game_state import GameState

# ── 駒の価値（チューニング対象） ──────────────────────────────────────────────
PIECE_VALUES: Dict[PieceType, int] = {
    PieceType.SUI: 100_000,
    PieceType.TAI: 700,
    PieceType.CHU: 600,
    PieceType.OZU: 550,
    PieceType.TSU: 500,
    PieceType.KIB: 450,
    PieceType.YAR: 400,
    PieceType.YUM: 350,
    PieceType.SAM: 350,
    PieceType.SHO: 300,
    PieceType.SHI: 300,
    PieceType.BOU: 300,
    PieceType.TOR: 250,
    PieceType.HYO: 100,
}

# 中央制御ボーナス（掛け算係数: ×3）
_CENTER = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 2, 2, 2, 1, 1, 0],
    [0, 1, 2, 3, 3, 3, 2, 1, 0],
    [0, 2, 3, 4, 5, 4, 3, 2, 0],
    [0, 2, 3, 5, 6, 5, 3, 2, 0],
    [0, 2, 3, 4, 5, 4, 3, 2, 0],
    [0, 1, 2, 3, 3, 3, 2, 1, 0],
    [0, 1, 1, 2, 2, 2, 1, 1, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0],
]


def evaluate_material(state: GameState, ai_player: str) -> int:
    """駒得評価（Phase B と同じ基盤）"""
    human = "white" if ai_player == "black" else "black"
    score = 0
    for row in state.board:
        for stack in row:
            for piece in stack:
                if piece.type == PieceType.SUI:
                    continue  # 帅は盤上にある = 生存中
                val = PIECE_VALUES.get(piece.type, 0)
                score += val if piece.owner == ai_player else -val

    for piece in state.hand_pieces.get(ai_player, []):
        score += int(PIECE_VALUES.get(piece.type, 0) * 0.8)
    for piece in state.hand_pieces.get(human, []):
        score -= int(PIECE_VALUES.get(piece.type, 0) * 0.8)
    return score


def evaluate_position(state: GameState, ai_player: str) -> int:
    """
    位置評価:
      - 中央制御ボーナス
      - 前進ボーナス（自陣を超えて進んだ駒）
      - スタック高さボーナス（積み重ねた駒は戦力が高い）
    """
    score = 0
    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            if not stack:
                continue
            top = stack[-1]
            if top.type == PieceType.SUI:
                continue

            height = len(stack)
            val = PIECE_VALUES.get(top.type, 0)

            center = _CENTER[r][c] * 3
            stack_bonus = int(val * 0.12 * (height - 1))

            # 前進: 初期配置（黒:6-8列、白:0-2列）を超えた分
            if top.owner == "black":
                forward = max(0, 6 - r) * 5
            else:
                forward = max(0, r - 2) * 5

            total = center + stack_bonus + forward
            score += total if top.owner == ai_player else -total
    return score


def evaluate_sui_safety(state: GameState, ai_player: str) -> int:
    """
    帅安全度評価:
      - 自分の帅の周囲3マス以内に敵駒がいるとペナルティ
      - 敵の帅が危険な状態なら逆にボーナス
    """
    score = 0
    human = "white" if ai_player == "black" else "black"

    for player, sign in [(ai_player, 1), (human, -1)]:
        enemy = "white" if player == "black" else "black"

        sui_r, sui_c = -1, -1
        for r in range(9):
            for c in range(9):
                for piece in state.board[r][c]:
                    if piece.type == PieceType.SUI and piece.owner == player:
                        sui_r, sui_c = r, c
                        break

        if sui_r < 0:
            continue

        danger = 0
        for dr in range(-3, 4):
            for dc in range(-3, 4):
                nr, nc = sui_r + dr, sui_c + dc
                if not (0 <= nr < 9 and 0 <= nc < 9):
                    continue
                s = state.board[nr][nc]
                if s and s[-1].owner == enemy:
                    dist = abs(dr) + abs(dc)
                    if dist <= 2:
                        danger -= (3 - dist) * 20

        score += sign * danger
    return score


def evaluate(state: GameState, ai_player: str) -> int:
    """Phase C 総合評価: 駒得 + 位置 + 帅安全度"""
    return (
        evaluate_material(state, ai_player)
        + evaluate_position(state, ai_player)
        + evaluate_sui_safety(state, ai_player)
    )
