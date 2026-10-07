"""
高速エンジン（Numba）用の定数テーブルと、GameState ⇔ 配列の変換。

駒コード: code = 駒種 * 2 + 手番 + 1（0 = 空）。駒種は PieceType の定義順、手番は 黒=0 / 白=1。
盤面: board[r, c, layer]（layer 0 = 最下段）, heights[r, c]
手駒: hands[手番, 駒種] = 枚数
手の表現（int64）: kind<<24 | fr<<20 | fc<<16 | tr<<12 | tc<<8 | extra
  kind: 0=通常移動/自駒へのツケ, 1=取る, 2=敵駒へのツケ, 3=新(手駒を打つ), 4=謀の寝返り
  extra: 新 → 駒種, 謀 → 寝返らせる段（0=最下段）
"""

import numpy as np

from models.piece import Piece, PieceType
from logic.piece_moves import (
    FIXED_MOVES, JUMP_MOVES, NORMAL_MOVES, JUMP_PIECES, TAI_SLIDE_DIRS, CHU_SLIDE_DIRS,
)
from logic.movement import _get_intermediate_squares
from logic.zobrist import HASHER

PIECE_TYPES = list(PieceType)
PT_INDEX = {pt: i for i, pt in enumerate(PIECE_TYPES)}
N_TYPES = len(PIECE_TYPES)

T_SUI = PT_INDEX[PieceType.SUI]
T_TAI = PT_INDEX[PieceType.TAI]
T_CHU = PT_INDEX[PieceType.CHU]
T_BOU = PT_INDEX[PieceType.BOU]

KIND_AUTO, KIND_CAPTURE, KIND_TSUKE_ENEMY, KIND_ARATA, KIND_BOUSHOU = 0, 1, 2, 3, 4
_ACTIONS = {KIND_AUTO: "auto", KIND_CAPTURE: "capture", KIND_TSUKE_ENEMY: "tsuke_enemy"}

# ── 移動オフセット: [駒種, 段数(1-3), 手番(0黒/1白), k] ─────────────────────────
MAX_OFFS = 32
MAX_PATH = 4
OFF_N = np.zeros((N_TYPES, 4, 2), np.int64)
OFF_DR = np.zeros((N_TYPES, 4, 2, MAX_OFFS), np.int64)
OFF_DC = np.zeros((N_TYPES, 4, 2, MAX_OFFS), np.int64)
OFF_JUMP = np.zeros((N_TYPES, 4, 2, MAX_OFFS), np.int64)
OFF_PLEN = np.zeros((N_TYPES, 4, 2, MAX_OFFS), np.int64)
OFF_PATH = np.zeros((N_TYPES, 4, 2, MAX_OFFS, MAX_PATH, 2), np.int64)
# 機動力評価用: 移動テーブルの要素数（+ スライド駒の近似値）
MOB = np.zeros((N_TYPES, 4), np.int64)
# スライド方向: 0=なし, 1=大(縦横), 2=中(斜め)
SLIDE_KIND = np.zeros(N_TYPES, np.int64)
SLIDE_DIRS = np.array([[(0, 0)] * 4, TAI_SLIDE_DIRS, CHU_SLIDE_DIRS], np.int64)
IS_JUMP_PIECE = np.zeros(N_TYPES, np.int64)
# 謀の寝返り評価・帅の逃げ場評価用（経路判定なしの固定移動テーブル）
FIX_N = np.zeros((N_TYPES, 4), np.int64)
FIX_DX = np.zeros((N_TYPES, 4, MAX_OFFS), np.int64)
FIX_DY = np.zeros((N_TYPES, 4, MAX_OFFS), np.int64)
JMP_N = np.zeros((N_TYPES, 4), np.int64)
JMP_DX = np.zeros((N_TYPES, 4, MAX_OFFS), np.int64)
JMP_DY = np.zeros((N_TYPES, 4, MAX_OFFS), np.int64)

for pt, ti in PT_INDEX.items():
    SLIDE_KIND[ti] = 1 if pt == PieceType.TAI else 2 if pt == PieceType.CHU else 0
    IS_JUMP_PIECE[ti] = 1 if pt in JUMP_PIECES else 0
    for h in (1, 2, 3):
        fixed = FIXED_MOVES.get(pt, {}).get(h, [])
        jump = JUMP_MOVES.get(pt, {}).get(h, [])
        normal = NORMAL_MOVES.get(pt, {}).get(h, [])
        MOB[ti, h] = len(fixed) + len(jump) + len(normal) + (18 if pt in (PieceType.TAI, PieceType.CHU) else 0)
        FIX_N[ti, h] = len(fixed)
        for k, (dx, dy) in enumerate(fixed):
            FIX_DX[ti, h, k], FIX_DY[ti, h, k] = dx, dy
        JMP_N[ti, h] = len(jump)
        for k, (dx, dy) in enumerate(jump):
            JMP_DX[ti, h, k], JMP_DY[ti, h, k] = dx, dy
        groups = [(jump, 1), (normal, 0)] if pt in JUMP_PIECES else [(fixed, 0)]
        for side, row_mult in ((0, -1), (1, 1)):
            k = 0
            for moves, is_jump in groups:
                for dx, dy in moves:
                    dr, dc = row_mult * dy, dx
                    path = _get_intermediate_squares(0, 0, dr, dc)
                    OFF_DR[ti, h, side, k], OFF_DC[ti, h, side, k] = dr, dc
                    OFF_JUMP[ti, h, side, k] = is_jump
                    OFF_PLEN[ti, h, side, k] = len(path)
                    for j, (pr, pc) in enumerate(path):
                        OFF_PATH[ti, h, side, k, j, 0] = pr
                        OFF_PATH[ti, h, side, k, j, 1] = pc
                    k += 1
            OFF_N[ti, h, side] = k

# ── Zobrist（Python 版 HASHER と同じ値を使い、対局履歴のハッシュと互換にする） ──
Z_BOARD = np.array(HASHER.board_table, dtype=np.uint64)          # [r, c, layer, type, owner]
Z_HAND = np.array(HASHER.hand_table, dtype=np.uint64)            # [type, owner, count]
Z_TURN = np.uint64(HASHER.turn_table)

CENTER = np.array([
    [0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 2, 2, 2, 1, 1, 0],
    [0, 1, 2, 3, 3, 3, 2, 1, 0],
    [0, 2, 3, 4, 5, 4, 3, 2, 0],
    [0, 2, 3, 5, 6, 5, 3, 2, 0],
    [0, 2, 3, 4, 5, 4, 3, 2, 0],
    [0, 1, 2, 3, 3, 3, 2, 1, 0],
    [0, 1, 1, 2, 2, 2, 1, 1, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0],
], np.float64)

# ── 評価関数の重み（配列化） ────────────────────────────────────────────────
W_CENTER, W_STACK_RATIO, W_FORWARD, W_MOBILITY, W_THREAT, W_SUI_THREAT, W_FORTRESS, \
    W_SAFETY_RADIUS, W_SAFETY_PENALTY, W_ISOLATED, W_BOU, W_SUI_MOB, W_RAY, W_HANGING, \
    W_FRONTLINE, W_ARATA, W_PHASE_OPEN, W_PHASE_END, W_HAS_HB, \
    W_KZ_ATTACK, W_SUI_CHECK, W_SUI_ESCAPE = range(22)


def weights_to_arrays(weights: dict):
    """evaluate.py の各関数と同じ既定値で重みを配列にする。"""
    g = weights.get
    w = np.zeros(22, np.float64)
    w[W_CENTER] = g("center_weight", 3)
    w[W_STACK_RATIO] = g("stack_bonus_ratio", 0.12)
    w[W_FORWARD] = g("forward_weight", 5)
    w[W_MOBILITY] = g("mobility_weight", 0)
    w[W_THREAT] = g("jumping_threat_weight", 0)
    w[W_SUI_THREAT] = g("jumping_sui_threat_weight", 0)
    w[W_FORTRESS] = g("sui_fortress_weight", 0)
    w[W_SAFETY_RADIUS] = g("sui_safety_radius", 3)
    w[W_SAFETY_PENALTY] = g("sui_safety_penalty", 20)
    w[W_ISOLATED] = g("isolated_penalty_ratio", 0)
    w[W_BOU] = g("bou_defect_weight", 0)
    w[W_SUI_MOB] = g("sui_mobility_weight", 0)
    w[W_RAY] = g("ray_blocking_weight", 0)
    w[W_HANGING] = g("hanging_penalty_ratio", 0)
    w[W_FRONTLINE] = g("frontline_weight", 0)
    w[W_ARATA] = g("arata_control_weight", 0)
    # 帥の周りへの攻め（高速エンジンのみ。Python 版の evaluate には無い）
    w[W_KZ_ATTACK] = g("sui_zone_attack_weight", 0)
    w[W_SUI_CHECK] = g("sui_check_weight", 0)
    w[W_SUI_ESCAPE] = g("sui_escape_weight", 0)
    th = g("phase_thresholds", {}) or {}
    w[W_PHASE_OPEN] = th.get("opening", 35)
    w[W_PHASE_END] = th.get("endgame", 19)
    hb = g("stack_height_bonus", []) or []
    w[W_HAS_HB] = 1.0 if hb else 0.0
    hb_arr = np.ones(3, np.float64)
    for i, v in enumerate(hb[:3]):
        hb_arr[i] = v

    from logic.ai.evaluate import _piece_values, PIECE_VALUES
    pv_map = _piece_values(weights) if g("piece_values") else PIECE_VALUES
    pv = np.zeros(N_TYPES, np.float64)
    for pt, ti in PT_INDEX.items():
        pv[ti] = pv_map.get(pt, 0)

    hr = g("hand_piece_ratio", 0.8)
    hand_ratio = np.zeros(3, np.float64)    # opening / middle / endgame
    for i, phase in enumerate(("opening", "middle", "endgame")):
        hand_ratio[i] = float(hr.get(phase, 1.2)) if isinstance(hr, dict) else float(hr)
    return w, pv, hb_arr, hand_ratio


# ── GameState ⇔ 配列 ────────────────────────────────────────────────────────

def state_to_arrays(state):
    board = np.zeros((9, 9, 3), np.int64)
    heights = np.zeros((9, 9), np.int64)
    for r in range(9):
        for c in range(9):
            st = state.board[r][c]
            heights[r, c] = len(st)
            for layer, p in enumerate(st[:3]):
                board[r, c, layer] = PT_INDEX[p.type] * 2 + (0 if p.owner == "black" else 1) + 1
    hands = np.zeros((2, N_TYPES), np.int64)
    for side, owner in ((0, "black"), (1, "white")):
        for p in state.hand_pieces.get(owner, []):
            hands[side, PT_INDEX[p.type]] += 1
    side = 0 if state.current_player == "black" else 1
    return board, heights, hands, side


def decode_move(m: int) -> tuple:
    """int64 の手を探索モジュールの手の形式（タプル）に戻す。"""
    m = int(m)
    kind = (m >> 24) & 0xF
    fr, fc, tr, tc, extra = (m >> 20) & 0xF, (m >> 16) & 0xF, (m >> 12) & 0xF, (m >> 8) & 0xF, m & 0xFF
    if kind == KIND_ARATA:
        return ("arata", PIECE_TYPES[extra].value, tr, tc)
    if kind == KIND_BOUSHOU:
        return ("boushou", fr, fc, tr, tc, extra)
    return ("board", fr, fc, tr, tc, _ACTIONS[kind])
