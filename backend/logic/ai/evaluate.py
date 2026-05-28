"""
評価関数 (Tier 0 / Tier 1 共通)。

weights=None のとき既定定数（Tier 0 後方互換）。
tier1.yaml を渡すと拡張特徴量が有効になる。

特徴量一覧:
  [共通]  駒得・位置・帥安全度
  [Tier1] スタック構造・機動力・跳び駒射線・帅囲い
          孤立駒ペナルティ・謀の動的価値
  [予定]  帅の逃げ場(G)・射線遮断(H) — 初期 weight=0
"""

from typing import Dict, Optional

from models.piece import PieceType
from models.game_state import GameState
from logic.piece_moves import FIXED_MOVES, JUMP_MOVES, NORMAL_MOVES, JUMP_PIECES, TAI_SLIDE_DIRS, CHU_SLIDE_DIRS
from logic.arata import get_valid_arata_positions
from logic.rules import check_boushou_defection

# ── Tier 0 既定値 ─────────────────────────────────────────────────────────────

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

# スタック高ボーナスの対象外（移動範囲がスタックに依存しない）
_NO_HEIGHT_BONUS = {PieceType.SUI, PieceType.TAI, PieceType.CHU}

# スライド駒の機動力近似（縦横/斜めスライドの平均到達マス数）
_SLIDE_MOBILITY = {PieceType.TAI: 18, PieceType.CHU: 18}


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def _piece_values(weights: Optional[dict]) -> Dict[PieceType, int]:
    if weights is None:
        return PIECE_VALUES
    pv_raw = weights.get("piece_values", {})
    return {PieceType[k]: v for k, v in pv_raw.items()} if pv_raw else PIECE_VALUES


def _hand_ratio(weights: Optional[dict], phase: str) -> float:
    """フェーズ別の手駒価値比率を返す（tier1 は dict、tier0 は scalar）。"""
    if weights is None:
        return 0.8
    hr = weights.get("hand_piece_ratio", 0.8)
    if isinstance(hr, dict):
        return float(hr.get(phase, 1.2))
    return float(hr)


# ── ゲームフェーズ ────────────────────────────────────────────────────────────

def get_game_phase(state: GameState, weights: Optional[dict] = None) -> str:
    """盤上の総駒数でフェーズを判定する。"""
    count = sum(len(s) for row in state.board for s in row)
    thresholds = weights.get("phase_thresholds", {}) if weights else {}
    opening_th = thresholds.get("opening", 35)
    endgame_th = thresholds.get("endgame", 19)
    if count >= opening_th:
        return "opening"
    if count <= endgame_th:
        return "endgame"
    return "middle"


# ── 駒得評価 ──────────────────────────────────────────────────────────────────

def evaluate_material(state: GameState, ai_player: str, weights: Optional[dict] = None) -> int:
    """
    駒得評価。
    手駒はフェーズ別比率で評価（tier1 は常に > 1.0 → 理由なしに打たない）。
    """
    piece_values = _piece_values(weights)
    phase = get_game_phase(state, weights)
    hand_ratio = _hand_ratio(weights, phase)
    human = "white" if ai_player == "black" else "black"
    score = 0

    for row in state.board:
        for stack in row:
            for piece in stack:
                if piece.type == PieceType.SUI:
                    continue
                val = piece_values.get(piece.type, 0)
                score += val if piece.owner == ai_player else -val

    for piece in state.hand_pieces.get(ai_player, []):
        score += int(piece_values.get(piece.type, 0) * hand_ratio)
    for piece in state.hand_pieces.get(human, []):
        score -= int(piece_values.get(piece.type, 0) * hand_ratio)

    return score


# ── 位置評価 ──────────────────────────────────────────────────────────────────

def evaluate_position(state: GameState, ai_player: str, weights: Optional[dict] = None) -> int:
    """
    位置評価（中央制御 + 前進度 + スタック高ボーナス旧式）。
    tier1 では stack_bonus_ratio=0 に設定し、
    スタック評価は evaluate_stack_structure に移管する。
    """
    piece_values = _piece_values(weights)
    center_w   = weights.get("center_weight",    3)    if weights else 3
    stack_ratio = weights.get("stack_bonus_ratio", 0.12) if weights else 0.12
    fwd_w      = weights.get("forward_weight",   5)    if weights else 5

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
            val = piece_values.get(top.type, 0)

            center      = _CENTER[r][c] * center_w
            stack_bonus = int(val * stack_ratio * (height - 1))

            if top.owner == "black":
                forward = max(0, 6 - r) * fwd_w
            else:
                forward = max(0, r - 2) * fwd_w

            total = center + stack_bonus + forward
            score += total if top.owner == ai_player else -total

    return score


# ── スタック構造評価 ──────────────────────────────────────────────────────────

def evaluate_stack_structure(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """
    スタック高さボーナス。
    帅・大・中はスライドで移動範囲が独立しているため対象外。
    tier0 weights には stack_height_bonus キーがないので自動的に 0 を返す。
    """
    if weights is None:
        return 0
    height_bonuses: list = weights.get("stack_height_bonus", [])
    if not height_bonuses:
        return 0

    piece_values = _piece_values(weights)
    score = 0

    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            height = len(stack)
            if height < 2:
                continue
            top = stack[-1]
            if top.type in _NO_HEIGHT_BONUS:
                continue

            val = piece_values.get(top.type, 0)
            idx = min(height, 3) - 1           # index 0/1/2
            bonus = int(val * (height_bonuses[idx] - 1.0))
            score += bonus if top.owner == ai_player else -bonus

    return score


# ── 機動力評価 ────────────────────────────────────────────────────────────────

def evaluate_mobility(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """
    機動力評価（移動テーブルのエントリ数による近似）。
    実際の経路チェックは省略し高速化。
    スライド駒（大/中）は定数で近似。
    """
    weight = weights.get("mobility_weight", 0) if weights else 0
    if weight == 0:
        return 0

    ai_mob = 0
    human_mob = 0

    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            if not stack:
                continue
            top = stack[-1]
            pt = top.type
            h = min(len(stack), 3)

            n = len(FIXED_MOVES.get(pt, {}).get(h, []))
            n += len(JUMP_MOVES.get(pt, {}).get(h, []))
            n += len(NORMAL_MOVES.get(pt, {}).get(h, []))
            n += _SLIDE_MOBILITY.get(pt, 0)

            if top.owner == ai_player:
                ai_mob += n
            else:
                human_mob += n

    return (ai_mob - human_mob) * weight


# ── 跳び駒射線評価 ────────────────────────────────────────────────────────────

def evaluate_jumping_threats(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """
    弩/筒/弓のジャンプ先に敵駒がいる場合のボーナス。
    敵帅を狙っている場合は大きなボーナス。
    （経路チェックは省略した近似値）
    """
    threat_w    = weights.get("jumping_threat_weight",     0) if weights else 0
    sui_threat_w = weights.get("jumping_sui_threat_weight", 0) if weights else 0
    if threat_w == 0 and sui_threat_w == 0:
        return 0

    score = 0

    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            if not stack:
                continue
            top = stack[-1]
            if top.type not in JUMP_PIECES:
                continue

            player   = top.owner
            row_mult = -1 if player == "black" else 1
            h        = min(len(stack), 3)
            sign     = 1 if player == ai_player else -1

            for dx, dy in JUMP_MOVES[top.type].get(h, []):
                tr = r + row_mult * dy
                tc = c + dx
                if not (0 <= tr < 9 and 0 <= tc < 9):
                    continue
                dst = state.board[tr][tc]
                if not dst or dst[-1].owner == player:
                    continue
                if dst[-1].type == PieceType.SUI:
                    score += sign * sui_threat_w
                else:
                    score += sign * threat_w

    return score


# ── 帅の囲い評価 ──────────────────────────────────────────────────────────────

def evaluate_sui_fortress(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """帅周辺8マスの自駒スタック厚みをボーナスとして評価する。"""
    fortress_w = weights.get("sui_fortress_weight", 0) if weights else 0
    if fortress_w == 0:
        return 0

    score = 0
    human = "white" if ai_player == "black" else "black"

    for player, sign in [(ai_player, 1), (human, -1)]:
        sui_r = sui_c = -1
        for r in range(9):
            for c in range(9):
                for p in state.board[r][c]:
                    if p.type == PieceType.SUI and p.owner == player:
                        sui_r, sui_c = r, c
                        break
        if sui_r < 0:
            continue

        thickness = 0
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = sui_r + dr, sui_c + dc
                if 0 <= nr < 9 and 0 <= nc < 9:
                    s = state.board[nr][nc]
                    if s and s[-1].owner == player:
                        thickness += len(s)

        score += sign * thickness * fortress_w

    return score


# ── 帅安全度評価 ──────────────────────────────────────────────────────────────

def evaluate_sui_safety(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """帅の周囲3マス以内に敵駒がいるとペナルティ。"""
    radius  = weights.get("sui_safety_radius",  3)  if weights else 3
    penalty = weights.get("sui_safety_penalty", 20) if weights else 20

    score = 0
    human = "white" if ai_player == "black" else "black"

    for player, sign in [(ai_player, 1), (human, -1)]:
        enemy = "white" if player == "black" else "black"
        sui_r = sui_c = -1
        for r in range(9):
            for c in range(9):
                for p in state.board[r][c]:
                    if p.type == PieceType.SUI and p.owner == player:
                        sui_r, sui_c = r, c
                        break

        if sui_r < 0:
            continue

        danger = 0
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                nr, nc = sui_r + dr, sui_c + dc
                if not (0 <= nr < 9 and 0 <= nc < 9):
                    continue
                s = state.board[nr][nc]
                if s and s[-1].owner == enemy:
                    dist = abs(dr) + abs(dc)
                    if dist <= 2:
                        danger -= (3 - dist) * penalty

        score += sign * danger

    return score


# ── 孤立駒ペナルティ ──────────────────────────────────────────────────────────

def evaluate_isolated_penalty(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """
    周囲8マスに自駒が一つもない駒（孤立駒）にペナルティを与える。
    帅は sui_safety で評価するため対象外。
    """
    ratio = weights.get("isolated_penalty_ratio", 0) if weights else 0
    if ratio == 0:
        return 0

    piece_values = _piece_values(weights)
    score = 0

    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            if not stack:
                continue
            top = stack[-1]
            if top.type == PieceType.SUI:
                continue

            has_neighbor = any(
                0 <= r + dr < 9
                and 0 <= c + dc < 9
                and state.board[r + dr][c + dc]
                and state.board[r + dr][c + dc][-1].owner == top.owner
                for dr in (-1, 0, 1)
                for dc in (-1, 0, 1)
                if dr != 0 or dc != 0
            )
            if not has_neighbor:
                val = piece_values.get(top.type, 0)
                penalty = int(val * ratio)
                score -= penalty if top.owner == ai_player else -penalty

    return score


# ── 謀の動的価値 ──────────────────────────────────────────────────────────────

def evaluate_bou_dynamic(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """
    謀がリーチできる敵スタック内に寝返り可能な駒がある場合、
    その駒価値に比例したボーナスを与える。
    """
    bou_w = weights.get("bou_defect_weight", 0) if weights else 0
    if bou_w == 0:
        return 0

    piece_values_map = _piece_values(weights)
    score = 0

    for player, sign in [(ai_player, 1),
                         ("white" if ai_player == "black" else "black", -1)]:
        hand     = state.hand_pieces.get(player, [])
        row_mult = -1 if player == "black" else 1

        for r in range(9):
            for c in range(9):
                stack = state.board[r][c]
                if not stack:
                    continue
                top = stack[-1]
                if top.type != PieceType.BOU or top.owner != player:
                    continue

                h = min(len(stack), 3)
                for dx, dy in FIXED_MOVES.get(PieceType.BOU, {}).get(h, []):
                    tr = r + row_mult * dy
                    tc = c + dx
                    if not (0 <= tr < 9 and 0 <= tc < 9):
                        continue
                    for _, pt in check_boushou_defection(
                        state.board, top, tr, tc, hand
                    ):
                        score += sign * int(piece_values_map.get(pt, 0) * bou_w)

    return score


# ── G: 帅の逃げ場（初期値 0） ─────────────────────────────────────────────────

def evaluate_sui_mobility(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """帅の逃げ場評価: 自帅の移動可能マス数 - 相手帅の移動可能マス数。"""
    weight = weights.get("sui_mobility_weight", 0) if weights else 0
    if weight == 0:
        return 0

    opponent = "white" if ai_player == "black" else "black"
    score = 0

    for player, sign in [(ai_player, 1), (opponent, -1)]:
        row_mult = -1 if player == "black" else 1
        for r in range(9):
            for c in range(9):
                stack = state.board[r][c]
                if not stack or stack[-1].type != PieceType.SUI or stack[-1].owner != player:
                    continue
                h = min(len(stack), 3)
                reachable = 0
                for dx, dy in FIXED_MOVES.get(PieceType.SUI, {}).get(h, []):
                    tr = r + row_mult * dy
                    tc = c + dx
                    if not (0 <= tr < 9 and 0 <= tc < 9):
                        continue
                    dst = state.board[tr][tc]
                    if not dst or dst[-1].owner != player:
                        reachable += 1
                score += sign * reachable

    return weight * score


# ── H: 射線遮断ペナルティ ────────────────────────────────────────────────────

def evaluate_ray_blocking(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """大/中のスライド射線を自駒が遮断している数をペナルティとして評価。"""
    weight = weights.get("ray_blocking_weight", 0) if weights else 0
    if weight == 0:
        return 0

    score = 0

    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            if not stack:
                continue
            top = stack[-1]
            if top.type == PieceType.TAI:
                dirs = TAI_SLIDE_DIRS
            elif top.type == PieceType.CHU:
                dirs = CHU_SLIDE_DIRS
            else:
                continue

            sign = 1 if top.owner == ai_player else -1

            for dr, dc in dirs:
                nr, nc = r + dr, c + dc
                while 0 <= nr < 9 and 0 <= nc < 9:
                    cell = state.board[nr][nc]
                    if cell:
                        if cell[-1].owner == top.owner:
                            # 友軍が射線を遮断 → ペナルティ
                            score -= sign * weight
                        break
                    nr += dr
                    nc += dc

    return score


# ── ぶら下がり駒ペナルティ ───────────────────────────────────────────────────

def evaluate_hanging_penalty(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """
    相手の合法手に取り手として含まれている自駒にペナルティを与える。
    探索の地平線外で取られる危険を静的評価に反映させる。
    state.rules が存在しない場合（Texel Tuning 等）はスキップ。
    """
    ratio = weights.get("hanging_penalty_ratio", 0) if weights else 0
    if ratio == 0:
        return 0
    if not hasattr(state, "rules"):
        return 0

    from logic.movement import get_valid_moves

    piece_values = _piece_values(weights)
    human = "white" if ai_player == "black" else "black"

    # 相手が次の手で取れるマスを列挙
    attacked: set = set()
    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            if not stack or stack[-1].owner != human:
                continue
            opts = get_valid_moves(
                state.board, r, c,
                state.rules.max_stack, state.rules.sui_can_tsuke,
            )
            for tr, tc in opts.valid_moves:
                dst = state.board[tr][tc]
                if dst and dst[-1].owner == ai_player:
                    attacked.add((tr, tc))

    score = 0
    for r, c in attacked:
        stack = state.board[r][c]
        if stack and stack[-1].owner == ai_player:
            top = stack[-1]
            if top.type == PieceType.SUI:
                continue  # 帅は evaluate_sui_safety で管理
            val = piece_values.get(top.type, 0)
            score -= int(val * ratio)

    return score


# ── 前線評価 ─────────────────────────────────────────────────────────────────

def evaluate_frontline(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """
    前線（最前列の自駒）が進んでいるほど新(arata)を打てる範囲が広がり有利。
    手駒がない場合は意味がないのでスキップ。
    """
    weight = weights.get("frontline_weight", 0) if weights else 0
    if weight == 0:
        return 0

    score = 0
    human = "white" if ai_player == "black" else "black"

    for player, sign in [(ai_player, 1), (human, -1)]:
        if not state.hand_pieces.get(player):
            continue  # 手駒なし → 前線評価不要

        frontmost: Optional[int] = None
        for r in range(9):
            for c in range(9):
                stack = state.board[r][c]
                if stack and stack[-1].owner == player:
                    if player == "black":
                        if frontmost is None or r < frontmost:
                            frontmost = r
                    else:
                        if frontmost is None or r > frontmost:
                            frontmost = r

        if frontmost is None:
            continue

        # 前進度: 黒は row 0 が最前（8-frontmost）、白は row 8 が最前（frontmost）
        advance = (8 - frontmost) if player == "black" else frontmost
        score += sign * advance * weight

    return score


# ── 新置きゾーン支配 ─────────────────────────────────────────────────────────

def evaluate_arata_control(
    state: GameState, ai_player: str, weights: Optional[dict] = None
) -> int:
    """
    有効な新置き(arata)マス数の差を評価。
    前線が進むほどアラタゾーンが広がる軍議特有のメカニクスを捉える。
    前方のマスほど高い重みをつける（前線を押し上げるインセンティブ）。
    """
    weight = weights.get("arata_control_weight", 0) if weights else 0
    if weight == 0:
        return 0

    max_stack = 3
    if hasattr(state, "rules") and state.rules:
        max_stack = getattr(state.rules, "max_stack", 3)

    opponent = "white" if ai_player == "black" else "black"

    def _weighted_spots(player: str) -> float:
        spots = get_valid_arata_positions(state.board, player, max_stack)
        total = 0.0
        for r, c in spots:
            forward = (8 - r) / 8.0 if player == "black" else r / 8.0
            total += 1.0 + forward  # 基本 1 + 前方ボーナス最大 1
        return total

    return int(weight * (_weighted_spots(ai_player) - _weighted_spots(opponent)))


# ── 総合評価 ──────────────────────────────────────────────────────────────────

def evaluate(state: GameState, ai_player: str, weights: Optional[dict] = None) -> int:
    """全特徴量を合算した局面スコアを返す。"""
    return (
        evaluate_material(state, ai_player, weights)
        + evaluate_position(state, ai_player, weights)
        + evaluate_stack_structure(state, ai_player, weights)
        + evaluate_mobility(state, ai_player, weights)
        + evaluate_jumping_threats(state, ai_player, weights)
        + evaluate_sui_fortress(state, ai_player, weights)
        + evaluate_sui_safety(state, ai_player, weights)
        + evaluate_isolated_penalty(state, ai_player, weights)
        + evaluate_bou_dynamic(state, ai_player, weights)
        + evaluate_sui_mobility(state, ai_player, weights)
        + evaluate_ray_blocking(state, ai_player, weights)
        + evaluate_hanging_penalty(state, ai_player, weights)
        + evaluate_frontline(state, ai_player, weights)
        + evaluate_arata_control(state, ai_player, weights)
    )
