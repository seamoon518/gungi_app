"""
AI engine entry point.
Phase A/B: setup は優先順位配置、game は alpha-beta 探索（難易度別パラメータ）
"""

import random
from typing import Tuple

from models.game_state import GameState
from models.piece import PieceType
from logic.setup import get_valid_setup_positions, has_placed_sui
from logic.game_engine import apply_move, apply_arata, apply_boushou, apply_setup_place, apply_setup_done
from logic.ai.search import find_best_move
from logic.ai.weights import load_weights

# setupフェーズの配置優先順（高価値→攻撃駒→守備駒）
_SETUP_PRIORITY = [
    PieceType.TAI, PieceType.CHU,
    PieceType.OZU, PieceType.TSU,
    PieceType.KIB, PieceType.YAR, PieceType.YUM,
    PieceType.SAM, PieceType.SHI, PieceType.BOU,
    PieceType.TOR, PieceType.SHO, PieceType.HYO,
]

# 難易度パラメータ（Tier 1: 共通評価関数 + 思考時間で差別化）
_DIFFICULTY_PARAMS = {
    "easy":   {"max_depth": 4,  "time_limit": 1.0,  "noise": 50, "max_moves": 20, "weights": "tier1"},
    "normal": {"max_depth": 8,  "time_limit": 3.0,  "noise": 10, "max_moves": 20, "weights": "tier1"},
    "hard":   {"max_depth": 12, "time_limit": 5.0,  "noise": 0,  "max_moves": 15, "weights": "tier1"},
}

# レベル別の深さ調整（time_limit 主導になったため全レベル 1.0 に統一）
_LEVEL_DEPTH_FACTOR: dict = {}


def get_ai_move_and_apply(state: GameState) -> Tuple[bool, str]:
    """AI の手を決定して state に直接適用する。"""
    if state.ai_player is None:
        return False, "AI プレイヤーが未設定です"
    if state.game_over:
        return False, "ゲームは終了しています"

    ai_player = state.ai_player

    if state.phase == "setup":
        return _handle_setup(state, ai_player)
    else:
        return _handle_game(state, ai_player)


# ── setup phase ──────────────────────────────────────────────────────────────

def _handle_setup(state: GameState, ai_player: str) -> Tuple[bool, str]:
    """初期配置フェーズ: 帅を置いてから他の駒を優先順で配置 → 済を宣言"""

    # 1) 帅が未配置なら後列中央に置く
    if not has_placed_sui(state.board, ai_player):
        valid = get_valid_setup_positions(state.board, ai_player, state.rules.max_stack)
        if not valid:
            return apply_setup_done(state)
        back_row = 8 if ai_player == "black" else 0
        back_valid = [p for p in valid if p[0] == back_row]
        pos = min(back_valid or valid, key=lambda p: abs(p[1] - 4))
        return apply_setup_place(state, PieceType.SUI.value, pos[0], pos[1])

    hand = state.hand_pieces.get(ai_player, [])
    valid = get_valid_setup_positions(state.board, ai_player, state.rules.max_stack)

    # 2) 盤上自駒数を確認
    board_count = sum(
        1 for row in state.board for stack in row
        for piece in stack if piece.owner == ai_player
    )

    # 3) 十分配置済み or 置き場なし → 済
    if not hand or not valid or board_count >= 13:
        return apply_setup_done(state)

    # 4) 優先順位の高い駒を選ぶ
    hand_types = {p.type for p in hand}
    piece_to_place = next(
        (pt for pt in _SETUP_PRIORITY if pt in hand_types),
        hand[0].type,
    )

    pos = random.choice(valid)
    return apply_setup_place(state, piece_to_place.value, pos[0], pos[1])


# ── game phase ────────────────────────────────────────────────────────────────

def _handle_game(state: GameState, ai_player: str) -> Tuple[bool, str]:
    """ゲームフェーズ: alpha-beta 探索で最善手を選択"""
    params = _DIFFICULTY_PARAMS.get(state.ai_difficulty or "easy", _DIFFICULTY_PARAMS["easy"])
    max_depth = params["max_depth"]
    weights = load_weights(params.get("weights", "tier1"))

    best = find_best_move(
        state,
        ai_player,
        max_depth=max_depth,
        time_limit=params["time_limit"],
        noise=params["noise"],
        max_moves=params["max_moves"],
        weights=weights,
    )

    if best is None:
        # 合法手なし（帅以外の駒が全滅など）→ AI投了
        state.game_over = True
        state.winner = "black" if ai_player == "white" else "white"
        return True, ""

    if best[0] == "board":
        _, fr, fc, tr, tc, action = best
        return apply_move(state, fr, fc, tr, tc, action)
    elif best[0] == "arata":
        _, pt_str, tr, tc = best
        return apply_arata(state, pt_str, tr, tc)
    elif best[0] == "boushou":
        _, fr, fc, tr, tc, target_index = best
        return apply_boushou(state, fr, fc, tr, tc, target_index)

    return False, "不明な手のタイプ"
