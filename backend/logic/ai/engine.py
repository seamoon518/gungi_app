"""
AI engine entry point.
setup は陣形どおりに配置、game は alpha-beta 探索（難易度別パラメータ）
"""

import random
from typing import Tuple

from models.game_state import GameState
from models.piece import PieceType
from logic.setup import get_valid_setup_positions, has_placed_sui
from logic.game_engine import apply_move, apply_arata, apply_boushou, apply_setup_place, apply_setup_done
from logic.ai.search import find_best_move
from logic.ai import fast as fast_engine
from logic.ai.weights import load_weights

# 難易度パラメータ（tier2評価関数 + 思考時間・ノイズで差別化）
_DIFFICULTY_PARAMS = {
    "easy":   {"max_depth": 4,  "time_limit": 1.0,  "noise": 50, "max_moves": 20, "weights": "tier2"},
    "normal": {"max_depth": 8,  "time_limit": 3.0,  "noise": 10, "max_moves": 20, "weights": "tier2"},
    "hard":   {"max_depth": 30, "time_limit": 5.0,  "noise": 0,  "max_moves": 15, "weights": "tier5"},
}

# レベル別の深さ調整（time_limit 主導になったため全レベル 1.0 に統一）
_LEVEL_DEPTH_FACTOR: dict = {}


def get_ai_move_and_apply(state: GameState) -> Tuple[bool, str]:
    """AI の手を決定して state に直接適用する。"""
    if state.ai_player is None:
        return False, "AI プレイヤーが未設定です"
    if state.game_over:
        return False, "ゲームは終了しています"

    # AI同士モードでは手番側プレイヤーが AI として動く
    ai_player = state.current_player if state.ai_player == "both" else state.ai_player

    if state.phase == "setup":
        return _handle_setup(state, ai_player)
    else:
        return _handle_game(state, ai_player)


# ── setup phase ──────────────────────────────────────────────────────────────

# 初期配置の陣形（白陣から見た (行, 列)。行 0 = 最後列）。
# 初級編の公式配置（rulebook.md）を土台に、特殊駒（砲・筒・謀）を加えたもの。
# 相手が早く「済」を宣言して配置が打ち切られても困らないよう、帥の守りから順に並べる。
_FORMATION = [
    (0, 4, PieceType.SUI),
    (0, 3, PieceType.CHU), (0, 5, PieceType.TAI),
    (1, 4, PieceType.YAR),
    (2, 3, PieceType.SAM), (2, 4, PieceType.HYO), (2, 5, PieceType.SAM),
    (2, 2, PieceType.TOR), (2, 6, PieceType.TOR),
    (1, 2, PieceType.YUM), (1, 6, PieceType.YUM),
    (1, 1, PieceType.KIB), (1, 7, PieceType.SHI),
    (2, 0, PieceType.HYO), (2, 8, PieceType.HYO),
    (0, 1, PieceType.OZU), (0, 7, PieceType.TSU),
    (1, 3, PieceType.BOU),
]


def _formation_for(player: str, mirror: bool) -> list:
    """陣形を手番側の座標に変換する（黒は 180° 回転。mirror=True で左右反転）。"""
    out = []
    for r, c, pt in _FORMATION:
        if mirror:
            c = 8 - c
        if player == "black":
            r, c = 8 - r, 8 - c
        out.append((r, c, pt))
    return out


def _handle_setup(state: GameState, ai_player: str) -> Tuple[bool, str]:
    """初期配置フェーズ: 陣形どおりに帥の守りから順に置き、置き終えたら済を宣言する"""
    valid = set(get_valid_setup_positions(state.board, ai_player, state.rules.max_stack))
    hand_types = {p.type for p in state.hand_pieces.get(ai_player, [])}
    # 左右反転するかは対局ごとに固定（盤面から決まる値を使い、手番ごとにぶれないようにする）
    mirror = (sum(len(st) for row in state.board for st in row) == 0 and random.random() < 0.5) \
        if not has_placed_sui(state.board, ai_player) else _is_mirrored(state, ai_player)

    for r, c, pt in _formation_for(ai_player, mirror):
        if pt in hand_types and not state.board[r][c] and (r, c) in valid:
            return apply_setup_place(state, pt.value, r, c)

    # 帥がまだ置けていない（通常は起こらない）ときだけ従来の方法で置く
    if not has_placed_sui(state.board, ai_player):
        back_row = 8 if ai_player == "black" else 0
        back_valid = [p for p in valid if p[0] == back_row] or list(valid)
        if not back_valid:
            return apply_setup_done(state)
        pos = min(back_valid, key=lambda p: abs(p[1] - 4))
        return apply_setup_place(state, PieceType.SUI.value, pos[0], pos[1])
    return apply_setup_done(state)


def _is_mirrored(state: GameState, ai_player: str) -> bool:
    """既に置いた駒が左右反転した陣形と一致するか（反転版の方が多く一致すれば True）"""
    def matches(m: bool) -> int:
        return sum(1 for r, c, pt in _formation_for(ai_player, m)
                   if state.board[r][c] and state.board[r][c][0].type == pt
                   and state.board[r][c][0].owner == ai_player)
    return matches(True) > matches(False)


# ── game phase ────────────────────────────────────────────────────────────────

def _handle_game(state: GameState, ai_player: str) -> Tuple[bool, str]:
    """ゲームフェーズ: alpha-beta 探索で最善手を選択"""
    # per-player 難易度（AI同士モード）→ fallback to ai_difficulty → "easy"
    if ai_player == "black":
        difficulty = state.ai_difficulty_black or state.ai_difficulty or "easy"
    elif ai_player == "white":
        difficulty = state.ai_difficulty_white or state.ai_difficulty or "easy"
    else:
        difficulty = state.ai_difficulty or "easy"
    params = _DIFFICULTY_PARAMS.get(difficulty, _DIFFICULTY_PARAMS["easy"])
    max_depth = params["max_depth"]
    weights = load_weights(params.get("weights", "tier1"))

    # コンパイル済みの高速エンジンが使えればそちらで探索する（結果は同じアルゴリズム）
    search = fast_engine.find_best_move_fast if fast_engine.ready() else find_best_move
    best = search(
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
        state.end_reason = "no_moves"
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
