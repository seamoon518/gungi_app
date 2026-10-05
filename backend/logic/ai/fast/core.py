"""
高速エンジン本体（Numba でコンパイルする）。

logic/movement.py・logic/ai/evaluate.py・logic/ai/search.py と同じ判定・評価・探索を
配列上で行う。Python 版との一致は tests/test_fast_engine.py で確認する。
"""

import numpy as np
from numba import njit

from logic.ai.fast.tables import (
    OFF_N, OFF_DR, OFF_DC, OFF_JUMP, OFF_PLEN, OFF_PATH, SLIDE_KIND, SLIDE_DIRS,
    IS_JUMP_PIECE, MOB, FIX_N, FIX_DX, FIX_DY, JMP_N, JMP_DX, JMP_DY,
    Z_BOARD, Z_HAND, Z_TURN, CENTER, N_TYPES, T_SUI, T_TAI, T_CHU, T_BOU,
    W_CENTER, W_STACK_RATIO, W_FORWARD, W_MOBILITY, W_THREAT, W_SUI_THREAT, W_FORTRESS,
    W_SAFETY_RADIUS, W_SAFETY_PENALTY, W_ISOLATED, W_BOU, W_SUI_MOB, W_RAY, W_HANGING,
    W_FRONTLINE, W_ARATA, W_PHASE_OPEN, W_PHASE_END, W_HAS_HB,
    KIND_AUTO, KIND_CAPTURE, KIND_TSUKE_ENEMY, KIND_ARATA, KIND_BOUSHOU,
)

# 手の並べ替えに使う駒価値（search.py の PIECE_VALUES と同じ Tier0 定数）
from logic.ai.evaluate import PIECE_VALUES as _PV0
from logic.ai.fast.tables import PT_INDEX as _PTI
ORDER_PV = np.zeros(N_TYPES, np.float64)
for _pt, _v in _PV0.items():
    ORDER_PV[_PTI[_pt]] = _v

MAX_PLY = 48
MAX_MOVES_GEN = 1024
TT_BITS = 20
TT_SIZE = 1 << TT_BITS
EV_BITS = 18
EV_SIZE = 1 << EV_BITS
TT_EXACT, TT_LOWER, TT_UPPER = 0, 1, 2
INF = 1e18


@njit(cache=True, inline="always")
def ptype(code):
    return (code - 1) >> 1


@njit(cache=True, inline="always")
def powner(code):
    return (code - 1) & 1


@njit(cache=True, inline="always")
def encode(kind, fr, fc, tr, tc, extra):
    return (kind << 24) | (fr << 20) | (fc << 16) | (tr << 12) | (tc << 8) | extra


# ── 合法手（movement.get_valid_moves と同じ順序・判定） ─────────────────────────

@njit(cache=True)
def valid_moves(board, heights, r, c, max_stack, sui_can_tsuke, out_r, out_c, out_et):
    """(r,c) の最上段の駒の移動先を out_* に書き、件数を返す。out_et[i]=1 は敵駒へのツケ可。"""
    h = heights[r, c]
    if h == 0:
        return 0
    code = board[r, c, h - 1]
    t = ptype(code)
    player = powner(code)
    no_tsuke = (t == T_SUI) and (sui_can_tsuke == 0)
    n = 0
    sk = SLIDE_KIND[t]
    if sk != 0:
        for d in range(4):
            dr = SLIDE_DIRS[sk, d, 0]
            dc = SLIDE_DIRS[sk, d, 1]
            r2 = r + dr
            c2 = c + dc
            while 0 <= r2 < 9 and 0 <= c2 < 9:
                h2 = heights[r2, c2]
                if h2 == 0:
                    out_r[n] = r2; out_c[n] = c2; out_et[n] = 0; n += 1
                else:
                    top2 = board[r2, c2, h2 - 1]
                    tsuke_ok = (not no_tsuke) and h2 < max_stack and h2 <= h and ptype(top2) != T_SUI
                    if powner(top2) == player:
                        if tsuke_ok:
                            out_r[n] = r2; out_c[n] = c2; out_et[n] = 0; n += 1
                    else:
                        if tsuke_ok or h2 <= h:
                            out_r[n] = r2; out_c[n] = c2; out_et[n] = 1 if tsuke_ok else 0; n += 1
                    break
                r2 += dr
                c2 += dc
    hh = h if h <= 3 else 3
    for k in range(OFF_N[t, hh, player]):
        r2 = r + OFF_DR[t, hh, player, k]
        c2 = c + OFF_DC[t, hh, player, k]
        if not (0 <= r2 < 9 and 0 <= c2 < 9):
            continue
        is_jump = OFF_JUMP[t, hh, player, k]
        blocked = False
        for j in range(OFF_PLEN[t, hh, player, k]):
            mh = heights[r + OFF_PATH[t, hh, player, k, j, 0], c + OFF_PATH[t, hh, player, k, j, 1]]
            if mh > 0 and (is_jump == 0 or mh > h):
                blocked = True
                break
        if blocked:
            continue
        h2 = heights[r2, c2]
        if h2 == 0:
            out_r[n] = r2; out_c[n] = c2; out_et[n] = 0; n += 1
            continue
        top2 = board[r2, c2, h2 - 1]
        tsuke_ok = (not no_tsuke) and h2 < max_stack and h2 <= h and ptype(top2) != T_SUI
        if powner(top2) == player:
            if tsuke_ok:
                out_r[n] = r2; out_c[n] = c2; out_et[n] = 0; n += 1
        else:
            if tsuke_ok or h2 <= h:
                out_r[n] = r2; out_c[n] = c2; out_et[n] = 1 if tsuke_ok else 0; n += 1
    return n


@njit(cache=True)
def arata_positions(board, heights, side, max_stack, out_r, out_c):
    front = -1
    for r in range(9):
        for c in range(9):
            h = heights[r, c]
            if h > 0 and powner(board[r, c, h - 1]) == side:
                if side == 0:
                    if front < 0 or r < front:
                        front = r
                else:
                    if front < 0 or r > front:
                        front = r
    if front < 0:
        return 0
    n = 0
    for r in range(9):
        if side == 0 and r < front:
            continue
        if side == 1 and r > front:
            continue
        for c in range(9):
            h = heights[r, c]
            if h == 0:
                out_r[n] = r; out_c[n] = c; n += 1
            else:
                top = board[r, c, h - 1]
                if powner(top) == side and h < max_stack and ptype(top) != T_SUI:
                    out_r[n] = r; out_c[n] = c; n += 1
    return n


@njit(cache=True)
def gen_moves(board, heights, hands, side, max_stack, sui_can_tsuke, out, captures_only):
    """search.get_all_game_moves（captures_only=1 なら _get_capture_moves）と同じ手を out に書く。"""
    vr = np.empty(64, np.int64)
    vc = np.empty(64, np.int64)
    ve = np.empty(64, np.int64)
    n = 0
    for r in range(9):
        for c in range(9):
            h = heights[r, c]
            if h == 0 or powner(board[r, c, h - 1]) != side:
                continue
            t = ptype(board[r, c, h - 1])
            k = valid_moves(board, heights, r, c, max_stack, sui_can_tsuke, vr, vc, ve)
            for i in range(k):
                tr = vr[i]
                tc = vc[i]
                h2 = heights[tr, tc]
                if h2 > 0 and powner(board[tr, tc, h2 - 1]) != side:
                    out[n] = encode(KIND_CAPTURE, r, c, tr, tc, 0); n += 1
                    if captures_only == 0 and ve[i] == 1:
                        out[n] = encode(KIND_TSUKE_ENEMY, r, c, tr, tc, 0); n += 1
                        if t == T_BOU:
                            for idx in range(h2):
                                pc = board[tr, tc, idx]
                                if powner(pc) != side and hands[side, ptype(pc)] > 0:
                                    out[n] = encode(KIND_BOUSHOU, r, c, tr, tc, idx); n += 1
                elif captures_only == 0:
                    out[n] = encode(KIND_AUTO, r, c, tr, tc, 0); n += 1
    if captures_only == 0:
        ar = np.empty(81, np.int64)
        ac = np.empty(81, np.int64)
        na = -1
        for t in range(N_TYPES):
            if hands[side, t] == 0:
                continue
            if na < 0:
                na = arata_positions(board, heights, side, max_stack, ar, ac)
            for i in range(na):
                out[n] = encode(KIND_ARATA, 0, 0, ar[i], ac[i], t); n += 1
    return n


# ── 指し手の適用（search._apply_move_inplace と同じ） ──────────────────────────

@njit(cache=True)
def make_move(board, heights, hands, side, m):
    """手を適用する。帥が取られて終局したら 1 を返す。"""
    kind = (m >> 24) & 0xF
    fr = (m >> 20) & 0xF
    fc = (m >> 16) & 0xF
    tr = (m >> 12) & 0xF
    tc = (m >> 8) & 0xF
    extra = m & 0xFF
    sui_taken = 0
    if kind == KIND_ARATA:
        hands[side, extra] -= 1
        board[tr, tc, heights[tr, tc]] = extra * 2 + side + 1
        heights[tr, tc] += 1
        return 0
    piece = board[fr, fc, heights[fr, fc] - 1]
    heights[fr, fc] -= 1
    board[fr, fc, heights[fr, fc]] = 0
    if kind == KIND_BOUSHOU:
        hands[side, ptype(board[tr, tc, extra])] -= 1
        board[tr, tc, extra] = ptype(board[tr, tc, extra]) * 2 + side + 1
        board[tr, tc, heights[tr, tc]] = piece
        heights[tr, tc] += 1
        return 0
    if kind == KIND_CAPTURE:
        while heights[tr, tc] > 0 and powner(board[tr, tc, heights[tr, tc] - 1]) != side:
            if ptype(board[tr, tc, heights[tr, tc] - 1]) == T_SUI:
                sui_taken = 1
            heights[tr, tc] -= 1
            board[tr, tc, heights[tr, tc]] = 0
    board[tr, tc, heights[tr, tc]] = piece
    heights[tr, tc] += 1
    return sui_taken


@njit(cache=True)
def compute_hash(board, heights, hands, side):
    hsh = np.uint64(0)
    for r in range(9):
        for c in range(9):
            for layer in range(heights[r, c]):
                code = board[r, c, layer]
                hsh ^= Z_BOARD[r, c, layer, ptype(code), powner(code)]
    for o in range(2):
        for t in range(N_TYPES):
            cnt = hands[o, t]
            if cnt > 0:
                hsh ^= Z_HAND[t, o, cnt if cnt <= 10 else 10]
    if side == 0:
        hsh ^= Z_TURN
    return hsh


# ── 評価関数（evaluate.evaluate と同じ） ──────────────────────────────────────

@njit(cache=True)
def _find_sui(board, heights, player):
    sr = -1
    sc = -1
    for r in range(9):
        for c in range(9):
            for layer in range(heights[r, c]):
                code = board[r, c, layer]
                if ptype(code) == T_SUI and powner(code) == player:
                    sr = r
                    sc = c
    return sr, sc


@njit(cache=True)
def evaluate(board, heights, hands, ai, max_stack, sui_can_tsuke, W, PV, HB, HR):
    human = 1 - ai
    score = 0.0

    # 駒得（フェーズ別の手駒比率）
    count = 0
    for r in range(9):
        for c in range(9):
            count += heights[r, c]
    if count >= W[W_PHASE_OPEN]:
        hand_ratio = HR[0]
    elif count <= W[W_PHASE_END]:
        hand_ratio = HR[2]
    else:
        hand_ratio = HR[1]
    for r in range(9):
        for c in range(9):
            for layer in range(heights[r, c]):
                code = board[r, c, layer]
                t = ptype(code)
                if t == T_SUI:
                    continue
                if powner(code) == ai:
                    score += PV[t]
                else:
                    score -= PV[t]
    for t in range(N_TYPES):
        for _ in range(hands[ai, t]):
            score += float(int(PV[t] * hand_ratio))
        for _ in range(hands[human, t]):
            score -= float(int(PV[t] * hand_ratio))

    # 位置・スタック構造・機動力・跳び駒・孤立・射線
    mob_ai = 0
    mob_hu = 0
    for r in range(9):
        for c in range(9):
            h = heights[r, c]
            if h == 0:
                continue
            top = board[r, c, h - 1]
            t = ptype(top)
            owner = powner(top)
            sign = 1.0 if owner == ai else -1.0
            hh = h if h <= 3 else 3
            if owner == ai:
                mob_ai += MOB[t, hh]
            else:
                mob_hu += MOB[t, hh]
            if t != T_SUI:
                center = CENTER[r, c] * W[W_CENTER]
                stack_bonus = float(int(PV[t] * W[W_STACK_RATIO] * (h - 1)))
                if owner == 0:
                    fwd = max(0, 6 - r) * W[W_FORWARD]
                else:
                    fwd = max(0, r - 2) * W[W_FORWARD]
                score += sign * (center + stack_bonus + fwd)
                if W[W_ISOLATED] != 0:
                    has_nb = False
                    for dr in range(-1, 2):
                        for dc in range(-1, 2):
                            if dr == 0 and dc == 0:
                                continue
                            nr = r + dr
                            nc = c + dc
                            if 0 <= nr < 9 and 0 <= nc < 9 and heights[nr, nc] > 0 \
                                    and powner(board[nr, nc, heights[nr, nc] - 1]) == owner:
                                has_nb = True
                    if not has_nb:
                        score -= sign * float(int(PV[t] * W[W_ISOLATED]))
            if W[W_HAS_HB] != 0 and h >= 2 and t != T_SUI and t != T_TAI and t != T_CHU:
                score += sign * float(int(PV[t] * (HB[hh - 1] - 1.0)))
            if IS_JUMP_PIECE[t] == 1 and (W[W_THREAT] != 0 or W[W_SUI_THREAT] != 0):
                rm = -1 if owner == 0 else 1
                for k in range(JMP_N[t, hh]):
                    tr = r + rm * JMP_DY[t, hh, k]
                    tc = c + JMP_DX[t, hh, k]
                    if not (0 <= tr < 9 and 0 <= tc < 9):
                        continue
                    h2 = heights[tr, tc]
                    if h2 == 0 or powner(board[tr, tc, h2 - 1]) == owner:
                        continue
                    if ptype(board[tr, tc, h2 - 1]) == T_SUI:
                        score += sign * W[W_SUI_THREAT]
                    else:
                        score += sign * W[W_THREAT]
            if W[W_RAY] != 0 and (t == T_TAI or t == T_CHU):
                sk = SLIDE_KIND[t]
                for d in range(4):
                    dr = SLIDE_DIRS[sk, d, 0]
                    dc = SLIDE_DIRS[sk, d, 1]
                    nr = r + dr
                    nc = c + dc
                    while 0 <= nr < 9 and 0 <= nc < 9:
                        if heights[nr, nc] > 0:
                            if powner(board[nr, nc, heights[nr, nc] - 1]) == owner:
                                score -= sign * W[W_RAY]
                            break
                        nr += dr
                        nc += dc
    if W[W_MOBILITY] != 0:
        score += (mob_ai - mob_hu) * W[W_MOBILITY]

    # 帥の囲い・帥の安全度・帥の逃げ場
    for pl in range(2):
        sign = 1.0 if pl == ai else -1.0
        sr, sc = _find_sui(board, heights, pl)
        if sr < 0:
            continue
        if W[W_FORTRESS] != 0:
            thick = 0
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    if dr == 0 and dc == 0:
                        continue
                    nr = sr + dr
                    nc = sc + dc
                    if 0 <= nr < 9 and 0 <= nc < 9 and heights[nr, nc] > 0 \
                            and powner(board[nr, nc, heights[nr, nc] - 1]) == pl:
                        thick += heights[nr, nc]
            score += sign * thick * W[W_FORTRESS]
        rad = int(W[W_SAFETY_RADIUS])
        danger = 0.0
        for dr in range(-rad, rad + 1):
            for dc in range(-rad, rad + 1):
                nr = sr + dr
                nc = sc + dc
                if not (0 <= nr < 9 and 0 <= nc < 9):
                    continue
                if heights[nr, nc] > 0 and powner(board[nr, nc, heights[nr, nc] - 1]) != pl:
                    dist = abs(dr) + abs(dc)
                    if dist <= 2:
                        danger -= (3 - dist) * W[W_SAFETY_PENALTY]
        score += sign * danger
    if W[W_SUI_MOB] != 0:
        sm = 0.0
        for pl in range(2):
            sign = 1.0 if pl == ai else -1.0
            rm = -1 if pl == 0 else 1
            for r in range(9):
                for c in range(9):
                    h = heights[r, c]
                    if h == 0:
                        continue
                    top = board[r, c, h - 1]
                    if ptype(top) != T_SUI or powner(top) != pl:
                        continue
                    hh = h if h <= 3 else 3
                    reach = 0
                    for k in range(FIX_N[T_SUI, hh]):
                        tr = r + rm * FIX_DY[T_SUI, hh, k]
                        tc = c + FIX_DX[T_SUI, hh, k]
                        if not (0 <= tr < 9 and 0 <= tc < 9):
                            continue
                        if heights[tr, tc] == 0 or powner(board[tr, tc, heights[tr, tc] - 1]) != pl:
                            reach += 1
                    sm += sign * reach
        score += W[W_SUI_MOB] * sm

    # 謀の寝返り（経路判定なしの近似、check_boushou_defection と同じ）
    if W[W_BOU] != 0:
        for pl in range(2):
            sign = 1.0 if pl == ai else -1.0
            rm = -1 if pl == 0 else 1
            for r in range(9):
                for c in range(9):
                    h = heights[r, c]
                    if h == 0:
                        continue
                    top = board[r, c, h - 1]
                    if ptype(top) != T_BOU or powner(top) != pl:
                        continue
                    hh = h if h <= 3 else 3
                    for k in range(FIX_N[T_BOU, hh]):
                        tr = r + rm * FIX_DY[T_BOU, hh, k]
                        tc = c + FIX_DX[T_BOU, hh, k]
                        if not (0 <= tr < 9 and 0 <= tc < 9):
                            continue
                        for layer in range(heights[tr, tc]):
                            pc = board[tr, tc, layer]
                            if powner(pc) != pl and hands[pl, ptype(pc)] > 0:
                                score += sign * float(int(PV[ptype(pc)] * W[W_BOU]))

    # 浮き駒（相手の次の手で取られる自駒）
    if W[W_HANGING] != 0:
        attacked = np.zeros((9, 9), np.int64)
        vr = np.empty(64, np.int64)
        vc = np.empty(64, np.int64)
        ve = np.empty(64, np.int64)
        for r in range(9):
            for c in range(9):
                h = heights[r, c]
                if h == 0 or powner(board[r, c, h - 1]) != human:
                    continue
                k = valid_moves(board, heights, r, c, max_stack, sui_can_tsuke, vr, vc, ve)
                for i in range(k):
                    h2 = heights[vr[i], vc[i]]
                    if h2 > 0 and powner(board[vr[i], vc[i], h2 - 1]) == ai:
                        attacked[vr[i], vc[i]] = 1
        for r in range(9):
            for c in range(9):
                if attacked[r, c] == 1:
                    top = board[r, c, heights[r, c] - 1]
                    if ptype(top) != T_SUI:
                        score -= float(int(PV[ptype(top)] * W[W_HANGING]))

    # 前線・新の支配
    for pl in range(2):
        sign = 1.0 if pl == ai else -1.0
        has_hand = False
        for t in range(N_TYPES):
            if hands[pl, t] > 0:
                has_hand = True
        if W[W_FRONTLINE] != 0 and has_hand:
            front = -1
            for r in range(9):
                for c in range(9):
                    h = heights[r, c]
                    if h > 0 and powner(board[r, c, h - 1]) == pl:
                        if pl == 0:
                            if front < 0 or r < front:
                                front = r
                        else:
                            if front < 0 or r > front:
                                front = r
            if front >= 0:
                adv = (8 - front) if pl == 0 else front
                score += sign * adv * W[W_FRONTLINE]
    if W[W_ARATA] != 0:
        ar = np.empty(81, np.int64)
        ac = np.empty(81, np.int64)
        tot = 0.0
        for pl in range(2):
            sign = 1.0 if pl == ai else -1.0
            na = arata_positions(board, heights, pl, max_stack, ar, ac)
            for i in range(na):
                fwd = (8 - ar[i]) / 8.0 if pl == 0 else ar[i] / 8.0
                tot += sign * (1.0 + fwd)
        score += float(int(W[W_ARATA] * tot))
    return score


@njit(cache=True)
def has_sui(board, heights, player):
    sr, sc = _find_sui(board, heights, player)
    return sr >= 0


# ── 探索（search.pvs / quiescence と同じアルゴリズム） ──────────────────────────

@njit(cache=True)
def _is_quiet(m):
    kind = (m >> 24) & 0xF
    return kind == KIND_AUTO or kind == KIND_ARATA


@njit(cache=True)
def _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val):
    key = compute_hash(B[ply], H[ply], HD[ply], SIDE[ply])
    idx = np.int64(key & np.uint64(EV_SIZE - 1))
    if ev_key[idx] == key and ev_val[idx] > -1e17:
        return ev_val[idx]
    v = evaluate(B[ply], H[ply], HD[ply], ai, P[0], P[1], W, PV, HB, HR)
    ev_key[idx] = key
    ev_val[idx] = v
    return v


@njit(cache=True)
def _child(B, H, HD, SIDE, ply, m):
    """ply の局面をコピーして手 m を指した局面を ply+1 に作る。帥を取ったら 1。"""
    B[ply + 1][:] = B[ply]
    H[ply + 1][:] = H[ply]
    HD[ply + 1][:] = HD[ply]
    over = make_move(B[ply + 1], H[ply + 1], HD[ply + 1], SIDE[ply], m)
    SIDE[ply + 1] = 1 - SIDE[ply]
    return over


@njit(cache=True, nogil=True)
def _tick(stats, deadline):
    # 時間切れは Python 側のタイマーが stats[1] = 1 を書き込んで知らせる
    # （Numba 内で時計を読むとキャッシュできなくなるため。探索中は GIL を解放している）
    stats[0] += 1
    return stats[1] == 1


# 静止探索（取る手だけを qdepth 手先（最大 6）まで読む。既定は 2）。search.quiescence と同じ判定。
# 再帰関数を別の再帰関数（pvs）から呼ぶと Numba のキャッシュ読み込みで落ちるため、
# 深さごとに関数を分けて再帰をなくしている（quiescence → _q5 → … → _q1 → _q0）。
@njit(cache=True, nogil=True)
def _q0(B, H, HD, SIDE, ply, ai, alpha, beta, qdepth, OVER, P, W, PV, HB, HR, ev_key, ev_val,
        stats, deadline, mbuf):
    """静止探索の末端（静的評価のみ）。"""
    if _tick(stats, deadline):
        return 0.0
    stand = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
    if SIDE[ply] == ai:
        if stand >= beta:
            return beta
    else:
        if stand <= alpha:
            return alpha
    return stand


@njit(cache=True, nogil=True)
def _q1(B, H, HD, SIDE, ply, ai, alpha, beta, qdepth, OVER, P, W, PV, HB, HR, ev_key, ev_val,
               stats, deadline, mbuf):
    if _tick(stats, deadline):
        return 0.0
    stand = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
    maximizing = SIDE[ply] == ai
    if maximizing:
        if stand >= beta:
            return beta
        alpha = max(alpha, stand)
    else:
        if stand <= alpha:
            return alpha
        beta = min(beta, stand)
    if qdepth == 0:
        return stand
    if OVER[ply] != 0:
        return 90000.0 if OVER[ply] - 1 == ai else -90000.0
    moves = mbuf[ply]
    n = gen_moves(B[ply], H[ply], HD[ply], SIDE[ply], P[0], P[1], moves, 1)
    # 取る駒の価値が高い順（安定ソート）
    keys = np.empty(n, np.float64)
    for i in range(n):
        tr = (moves[i] >> 12) & 0xF
        tc = (moves[i] >> 8) & 0xF
        keys[i] = -ORDER_PV[ptype(B[ply][tr, tc, H[ply][tr, tc] - 1])]
    order = np.argsort(keys, kind="mergesort")
    ordered = moves[:n][order].copy()
    for i in range(n):
        over = _child(B, H, HD, SIDE, ply, ordered[i])
        OVER[ply + 1] = (SIDE[ply] + 1) if over == 1 else 0
        v = _q0(B, H, HD, SIDE, ply + 1, ai, alpha, beta, qdepth - 1, OVER, P, W, PV, HB, HR,
                  ev_key, ev_val, stats, deadline, mbuf)
        if stats[1] == 1:
            return 0.0
        if maximizing:
            if v >= beta:
                return beta
            alpha = max(alpha, v)
        else:
            if v <= alpha:
                return alpha
            beta = min(beta, v)
    return alpha if maximizing else beta


@njit(cache=True, nogil=True)
def _q2(B, H, HD, SIDE, ply, ai, alpha, beta, qdepth, OVER, P, W, PV, HB, HR, ev_key, ev_val,
               stats, deadline, mbuf):
    if _tick(stats, deadline):
        return 0.0
    stand = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
    maximizing = SIDE[ply] == ai
    if maximizing:
        if stand >= beta:
            return beta
        alpha = max(alpha, stand)
    else:
        if stand <= alpha:
            return alpha
        beta = min(beta, stand)
    if qdepth == 0:
        return stand
    if OVER[ply] != 0:
        return 90000.0 if OVER[ply] - 1 == ai else -90000.0
    moves = mbuf[ply]
    n = gen_moves(B[ply], H[ply], HD[ply], SIDE[ply], P[0], P[1], moves, 1)
    # 取る駒の価値が高い順（安定ソート）
    keys = np.empty(n, np.float64)
    for i in range(n):
        tr = (moves[i] >> 12) & 0xF
        tc = (moves[i] >> 8) & 0xF
        keys[i] = -ORDER_PV[ptype(B[ply][tr, tc, H[ply][tr, tc] - 1])]
    order = np.argsort(keys, kind="mergesort")
    ordered = moves[:n][order].copy()
    for i in range(n):
        over = _child(B, H, HD, SIDE, ply, ordered[i])
        OVER[ply + 1] = (SIDE[ply] + 1) if over == 1 else 0
        v = _q1(B, H, HD, SIDE, ply + 1, ai, alpha, beta, qdepth - 1, OVER, P, W, PV, HB, HR,
                  ev_key, ev_val, stats, deadline, mbuf)
        if stats[1] == 1:
            return 0.0
        if maximizing:
            if v >= beta:
                return beta
            alpha = max(alpha, v)
        else:
            if v <= alpha:
                return alpha
            beta = min(beta, v)
    return alpha if maximizing else beta


@njit(cache=True, nogil=True)
def _q3(B, H, HD, SIDE, ply, ai, alpha, beta, qdepth, OVER, P, W, PV, HB, HR, ev_key, ev_val,
               stats, deadline, mbuf):
    if _tick(stats, deadline):
        return 0.0
    stand = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
    maximizing = SIDE[ply] == ai
    if maximizing:
        if stand >= beta:
            return beta
        alpha = max(alpha, stand)
    else:
        if stand <= alpha:
            return alpha
        beta = min(beta, stand)
    if qdepth == 0:
        return stand
    if OVER[ply] != 0:
        return 90000.0 if OVER[ply] - 1 == ai else -90000.0
    moves = mbuf[ply]
    n = gen_moves(B[ply], H[ply], HD[ply], SIDE[ply], P[0], P[1], moves, 1)
    # 取る駒の価値が高い順（安定ソート）
    keys = np.empty(n, np.float64)
    for i in range(n):
        tr = (moves[i] >> 12) & 0xF
        tc = (moves[i] >> 8) & 0xF
        keys[i] = -ORDER_PV[ptype(B[ply][tr, tc, H[ply][tr, tc] - 1])]
    order = np.argsort(keys, kind="mergesort")
    ordered = moves[:n][order].copy()
    for i in range(n):
        over = _child(B, H, HD, SIDE, ply, ordered[i])
        OVER[ply + 1] = (SIDE[ply] + 1) if over == 1 else 0
        v = _q2(B, H, HD, SIDE, ply + 1, ai, alpha, beta, qdepth - 1, OVER, P, W, PV, HB, HR,
                  ev_key, ev_val, stats, deadline, mbuf)
        if stats[1] == 1:
            return 0.0
        if maximizing:
            if v >= beta:
                return beta
            alpha = max(alpha, v)
        else:
            if v <= alpha:
                return alpha
            beta = min(beta, v)
    return alpha if maximizing else beta


@njit(cache=True, nogil=True)
def _q4(B, H, HD, SIDE, ply, ai, alpha, beta, qdepth, OVER, P, W, PV, HB, HR, ev_key, ev_val,
               stats, deadline, mbuf):
    if _tick(stats, deadline):
        return 0.0
    stand = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
    maximizing = SIDE[ply] == ai
    if maximizing:
        if stand >= beta:
            return beta
        alpha = max(alpha, stand)
    else:
        if stand <= alpha:
            return alpha
        beta = min(beta, stand)
    if qdepth == 0:
        return stand
    if OVER[ply] != 0:
        return 90000.0 if OVER[ply] - 1 == ai else -90000.0
    moves = mbuf[ply]
    n = gen_moves(B[ply], H[ply], HD[ply], SIDE[ply], P[0], P[1], moves, 1)
    # 取る駒の価値が高い順（安定ソート）
    keys = np.empty(n, np.float64)
    for i in range(n):
        tr = (moves[i] >> 12) & 0xF
        tc = (moves[i] >> 8) & 0xF
        keys[i] = -ORDER_PV[ptype(B[ply][tr, tc, H[ply][tr, tc] - 1])]
    order = np.argsort(keys, kind="mergesort")
    ordered = moves[:n][order].copy()
    for i in range(n):
        over = _child(B, H, HD, SIDE, ply, ordered[i])
        OVER[ply + 1] = (SIDE[ply] + 1) if over == 1 else 0
        v = _q3(B, H, HD, SIDE, ply + 1, ai, alpha, beta, qdepth - 1, OVER, P, W, PV, HB, HR,
                  ev_key, ev_val, stats, deadline, mbuf)
        if stats[1] == 1:
            return 0.0
        if maximizing:
            if v >= beta:
                return beta
            alpha = max(alpha, v)
        else:
            if v <= alpha:
                return alpha
            beta = min(beta, v)
    return alpha if maximizing else beta


@njit(cache=True, nogil=True)
def _q5(B, H, HD, SIDE, ply, ai, alpha, beta, qdepth, OVER, P, W, PV, HB, HR, ev_key, ev_val,
               stats, deadline, mbuf):
    if _tick(stats, deadline):
        return 0.0
    stand = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
    maximizing = SIDE[ply] == ai
    if maximizing:
        if stand >= beta:
            return beta
        alpha = max(alpha, stand)
    else:
        if stand <= alpha:
            return alpha
        beta = min(beta, stand)
    if qdepth == 0:
        return stand
    if OVER[ply] != 0:
        return 90000.0 if OVER[ply] - 1 == ai else -90000.0
    moves = mbuf[ply]
    n = gen_moves(B[ply], H[ply], HD[ply], SIDE[ply], P[0], P[1], moves, 1)
    # 取る駒の価値が高い順（安定ソート）
    keys = np.empty(n, np.float64)
    for i in range(n):
        tr = (moves[i] >> 12) & 0xF
        tc = (moves[i] >> 8) & 0xF
        keys[i] = -ORDER_PV[ptype(B[ply][tr, tc, H[ply][tr, tc] - 1])]
    order = np.argsort(keys, kind="mergesort")
    ordered = moves[:n][order].copy()
    for i in range(n):
        over = _child(B, H, HD, SIDE, ply, ordered[i])
        OVER[ply + 1] = (SIDE[ply] + 1) if over == 1 else 0
        v = _q4(B, H, HD, SIDE, ply + 1, ai, alpha, beta, qdepth - 1, OVER, P, W, PV, HB, HR,
                  ev_key, ev_val, stats, deadline, mbuf)
        if stats[1] == 1:
            return 0.0
        if maximizing:
            if v >= beta:
                return beta
            alpha = max(alpha, v)
        else:
            if v <= alpha:
                return alpha
            beta = min(beta, v)
    return alpha if maximizing else beta


@njit(cache=True, nogil=True)
def quiescence(B, H, HD, SIDE, ply, ai, alpha, beta, qdepth, OVER, P, W, PV, HB, HR, ev_key, ev_val,
               stats, deadline, mbuf):
    if _tick(stats, deadline):
        return 0.0
    stand = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
    maximizing = SIDE[ply] == ai
    if maximizing:
        if stand >= beta:
            return beta
        alpha = max(alpha, stand)
    else:
        if stand <= alpha:
            return alpha
        beta = min(beta, stand)
    if qdepth == 0:
        return stand
    if OVER[ply] != 0:
        return 90000.0 if OVER[ply] - 1 == ai else -90000.0
    moves = mbuf[ply]
    n = gen_moves(B[ply], H[ply], HD[ply], SIDE[ply], P[0], P[1], moves, 1)
    # 取る駒の価値が高い順（安定ソート）
    keys = np.empty(n, np.float64)
    for i in range(n):
        tr = (moves[i] >> 12) & 0xF
        tc = (moves[i] >> 8) & 0xF
        keys[i] = -ORDER_PV[ptype(B[ply][tr, tc, H[ply][tr, tc] - 1])]
    order = np.argsort(keys, kind="mergesort")
    ordered = moves[:n][order].copy()
    for i in range(n):
        over = _child(B, H, HD, SIDE, ply, ordered[i])
        OVER[ply + 1] = (SIDE[ply] + 1) if over == 1 else 0
        v = _q5(B, H, HD, SIDE, ply + 1, ai, alpha, beta, qdepth - 1, OVER, P, W, PV, HB, HR,
                  ev_key, ev_val, stats, deadline, mbuf)
        if stats[1] == 1:
            return 0.0
        if maximizing:
            if v >= beta:
                return beta
            alpha = max(alpha, v)
        else:
            if v <= alpha:
                return alpha
            beta = min(beta, v)
    return alpha if maximizing else beta


# ── PVS（search.pvs と同じアルゴリズムを、再帰を使わず明示的なスタックで実行する） ────────
# Numba は再帰関数をキャッシュから読み込むと落ちるため、各深さの状態を配列（フレーム）に持ち、
# 「子局面を探索する」「子の結果を受け取る」をループで処理する。
# ステージ: 子の探索を終えたあとにどこから再開するかを表す。
LOSS_SCORE = 90000.0   # これ以上（以下）は勝ち（負け）が確定した評価値

ST_ENTER, ST_AFTER_NULL, ST_GEN, ST_NEXT, ST_AFTER_S1, ST_AFTER_S2, ST_AFTER_S3, ST_FINISH = 0, 1, 2, 3, 4, 5, 6, 7


@njit(cache=True, nogil=True)
def _order(B, H, ply, n, depth, killers, hist, moves, out):
    """手の並べ替え: 取る > キラー > 謀 > 敵へのツケ > 履歴 > 新 > その他（安定ソート）。"""
    keys = np.empty(n, np.float64)
    for i in range(n):
        m = moves[i]
        kind = (m >> 24) & 0xF
        if kind == KIND_CAPTURE:
            fr = (m >> 20) & 0xF; fc = (m >> 16) & 0xF; tr = (m >> 12) & 0xF; tc = (m >> 8) & 0xF
            victim = ORDER_PV[ptype(B[ply][tr, tc, H[ply][tr, tc] - 1])]
            attacker = ORDER_PV[ptype(B[ply][fr, fc, H[ply][fr, fc] - 1])]
            pri = 20000.0 + victim * 10 - attacker
        elif kind == KIND_AUTO or kind == KIND_TSUKE_ENEMY:
            if depth < killers.shape[0] and m == killers[depth, 0]:
                pri = 10000.0
            elif depth < killers.shape[0] and m == killers[depth, 1]:
                pri = 9000.0
            elif kind == KIND_TSUKE_ENEMY:
                pri = 1000.0
            else:
                pri = float(hist[(m >> 20) & 0xF, (m >> 16) & 0xF, (m >> 12) & 0xF, (m >> 8) & 0xF])
        elif kind == KIND_BOUSHOU:
            pri = 1500.0
        else:
            pri = 500.0
        keys[i] = -pri
    order = np.argsort(keys, kind="mergesort")
    for i in range(n):
        out[i] = moves[order[i]]


@njit(cache=True, nogil=True)
def pvs(B, H, HD, SIDE, root_ply, ai, depth, alpha, beta, null_ok, OVER, P, W, PV, HB, HR,
        tt_k, tt_i, tt_s, killers, hist, ev_key, ev_val, path, hist_keys, hist_cnt,
        stats, deadline, mbuf, max_moves):
    n_ply = B.shape[0]
    f_depth = np.zeros(n_ply, np.int64)
    f_alpha = np.zeros(n_ply, np.float64)
    f_beta = np.zeros(n_ply, np.float64)
    f_null = np.zeros(n_ply, np.bool_)
    f_stage = np.zeros(n_ply, np.int64)
    f_i = np.zeros(n_ply, np.int64)
    f_n = np.zeros(n_ply, np.int64)
    f_ntot = np.zeros(n_ply, np.int64)
    f_red = np.zeros(n_ply, np.int64)
    f_best = np.zeros(n_ply, np.float64)
    f_bmove = np.zeros(n_ply, np.int64)
    f_oalpha = np.zeros(n_ply, np.float64)
    f_ttmove = np.zeros(n_ply, np.int64)
    f_idx = np.zeros(n_ply, np.int64)
    f_key = np.zeros(n_ply, np.uint64)
    obuf = np.zeros((n_ply, mbuf.shape[1]), np.int64)

    ply = root_ply
    f_depth[ply] = depth
    f_alpha[ply] = alpha
    f_beta[ply] = beta
    f_null[ply] = null_ok
    f_stage[ply] = ST_ENTER
    ret = 0.0
    returning = False   # True: この反復で ret を親へ返す

    while True:
        if returning:
            returning = False
            if ply == root_ply:
                return ret
            ply -= 1
            if stats[1] == 1:
                return 0.0
        st = f_stage[ply]
        d = f_depth[ply]
        side = SIDE[ply]
        maximizing = side == ai

        if st == ST_ENTER:
            if _tick(stats, deadline):
                return 0.0
            key = compute_hash(B[ply], H[ply], HD[ply], side)
            # 千日手回避: 実対局の出現回数 + 探索経路上の出現回数が 3 以上なら引き分け扱い
            gi = np.searchsorted(hist_keys, key)
            gc = hist_cnt[gi] if gi < hist_keys.shape[0] and hist_keys[gi] == key else 0
            pc = 0
            for k in range(1, ply):
                if path[k] == key:
                    pc += 1
            if gc + pc >= 3:
                ret = 0.0
                returning = True
                continue
            path[ply] = key
            idx = np.int64(key & np.uint64(TT_SIZE - 1))
            f_key[ply] = key
            f_idx[ply] = idx
            f_ttmove[ply] = -1
            a = f_alpha[ply]
            bt = f_beta[ply]
            if tt_k[idx] == key and tt_i[idx, 0] >= 0:
                f_ttmove[ply] = tt_i[idx, 2]
                if tt_i[idx, 0] >= d:
                    sc = tt_s[idx]
                    fl = tt_i[idx, 1]
                    if fl == TT_EXACT:
                        ret = sc
                        returning = True
                        continue
                    if fl == TT_LOWER:
                        a = max(a, sc)
                    elif fl == TT_UPPER:
                        bt = min(bt, sc)
                    if a >= bt:
                        ret = sc
                        returning = True
                        continue
            f_alpha[ply] = a
            f_beta[ply] = bt
            if OVER[ply] != 0:
                ret = (100000.0 + d) if OVER[ply] - 1 == ai else (-100000.0 - d)
                returning = True
                continue
            if d == 0:
                ret = quiescence(B, H, HD, SIDE, ply, ai, a, bt, P[2], OVER, P, W, PV, HB, HR,
                                 ev_key, ev_val, stats, deadline, mbuf)
                returning = True
                continue
            # Null Move（P[3]=1 なら AI 側だけでなく相手側の手番でも行う）
            if f_null[ply] and d >= 3 and (maximizing or P[3] == 1):
                se = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
                if (maximizing and se >= bt) or ((not maximizing) and se <= a):
                    B[ply + 1][:] = B[ply]
                    H[ply + 1][:] = H[ply]
                    HD[ply + 1][:] = HD[ply]
                    SIDE[ply + 1] = 1 - side
                    OVER[ply + 1] = 0
                    f_stage[ply] = ST_AFTER_NULL
                    ply += 1
                    f_depth[ply] = d - 3
                    if maximizing:
                        f_alpha[ply] = bt - 1
                        f_beta[ply] = bt
                    else:
                        f_alpha[ply] = a
                        f_beta[ply] = a + 1
                    f_null[ply] = False
                    f_stage[ply] = ST_ENTER
                    continue
            f_stage[ply] = ST_GEN
            continue

        if st == ST_AFTER_NULL:
            if maximizing and ret >= f_beta[ply]:
                ret = f_beta[ply]
                returning = True
                continue
            if (not maximizing) and ret <= f_alpha[ply]:
                ret = f_alpha[ply]
                returning = True
                continue
            f_stage[ply] = ST_GEN
            continue

        if st == ST_GEN:
            n = gen_moves(B[ply], H[ply], HD[ply], side, P[0], P[1], mbuf[ply], 0)
            if n == 0:
                ret = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
                returning = True
                continue
            _order(B, H, ply, n, d, killers, hist, mbuf[ply], obuf[ply])
            tm = f_ttmove[ply]
            if tm >= 0:
                for i in range(n):
                    if obuf[ply, i] == tm:
                        for j in range(i, 0, -1):
                            obuf[ply, j] = obuf[ply, j - 1]
                        obuf[ply, 0] = tm
                        break
            f_n[ply] = n if n <= max_moves else max_moves
            f_ntot[ply] = n
            f_i[ply] = 0
            f_best[ply] = -INF if maximizing else INF
            f_bmove[ply] = -1
            f_oalpha[ply] = f_alpha[ply]
            f_stage[ply] = ST_NEXT
            continue

        if st == ST_NEXT:
            i = f_i[ply]
            if i >= f_n[ply]:
                # 上位の候補手がすべて負け（詰み）なら、削った残りの手も読む（受けの見落としで偽の詰みを読まないため）
                if f_n[ply] < f_ntot[ply] and ((maximizing and f_best[ply] <= -LOSS_SCORE)
                                               or ((not maximizing) and f_best[ply] >= LOSS_SCORE)):
                    f_n[ply] = f_ntot[ply]
                else:
                    f_stage[ply] = ST_FINISH
                    continue
            m = obuf[ply, i]
            over = _child(B, H, HD, SIDE, ply, m)
            OVER[ply + 1] = (side + 1) if over == 1 else 0
            red = 1 if (d >= 3 and i >= 4 and _is_quiet(m)) else 0
            if red == 1 and P[4] == 1 and d >= 5 and i >= 8:
                red = 2   # P[4]=1: 深い局面のかなり後ろの静かな手はさらに浅く読む
            f_red[ply] = red
            a = f_alpha[ply]
            bt = f_beta[ply]
            if i == 0:
                cd, ca, cb = d - 1, a, bt
                f_stage[ply] = ST_AFTER_S3
            elif maximizing:
                cd, ca, cb = d - 1 - red, a, a + 1
                f_stage[ply] = ST_AFTER_S1
            else:
                cd, ca, cb = d - 1 - red, bt - 1, bt
                f_stage[ply] = ST_AFTER_S1
            ply += 1
            f_depth[ply] = cd
            f_alpha[ply] = ca
            f_beta[ply] = cb
            f_null[ply] = True
            f_stage[ply] = ST_ENTER
            continue

        if st == ST_AFTER_S1 or st == ST_AFTER_S2:
            v = ret
            a = f_alpha[ply]
            bt = f_beta[ply]
            m = obuf[ply, f_i[ply]]
            research = False
            if st == ST_AFTER_S1 and f_red[ply] > 0 and ((maximizing and v > a) or ((not maximizing) and v < bt)):
                # LMR で浅く読んだ手が良さそうなら、本来の深さで零窓探索し直す
                cd = d - 1
                ca, cb = (a, a + 1) if maximizing else (bt - 1, bt)
                f_stage[ply] = ST_AFTER_S2
                research = True
            elif v > a and v < bt:
                # 零窓探索が窓の内側に入ったら、全窓で探索し直す
                cd, ca, cb = d - 1, a, bt
                f_stage[ply] = ST_AFTER_S3
                research = True
            if research:
                over = _child(B, H, HD, SIDE, ply, m)
                OVER[ply + 1] = (side + 1) if over == 1 else 0
                ply += 1
                f_depth[ply] = cd
                f_alpha[ply] = ca
                f_beta[ply] = cb
                f_null[ply] = True
                f_stage[ply] = ST_ENTER
                continue
            f_stage[ply] = ST_AFTER_S3   # 再探索なし: この値で更新する
            continue

        if st == ST_AFTER_S3:
            v = ret
            m = obuf[ply, f_i[ply]]
            if maximizing:
                if v > f_best[ply]:
                    f_best[ply] = v
                    f_bmove[ply] = m
                f_alpha[ply] = max(f_alpha[ply], f_best[ply])
            else:
                if v < f_best[ply]:
                    f_best[ply] = v
                    f_bmove[ply] = m
                f_beta[ply] = min(f_beta[ply], f_best[ply])
            if f_alpha[ply] >= f_beta[ply]:
                if _is_quiet(m):
                    if d < killers.shape[0] and killers[d, 0] != m:
                        killers[d, 1] = killers[d, 0]
                        killers[d, 0] = m
                    if ((m >> 24) & 0xF) == KIND_AUTO:
                        fr = (m >> 20) & 0xF; fc = (m >> 16) & 0xF; tr = (m >> 12) & 0xF; tc = (m >> 8) & 0xF
                        hist[fr, fc, tr, tc] = min(hist[fr, fc, tr, tc] + d * d, 8000)
                f_stage[ply] = ST_FINISH
                continue
            f_i[ply] += 1
            f_stage[ply] = ST_NEXT
            continue

        # ST_FINISH: 置換表に保存して親へ返す
        if f_bmove[ply] >= 0:
            best = f_best[ply]
            if best <= f_oalpha[ply]:
                flag = TT_UPPER
            elif best >= f_beta[ply]:
                flag = TT_LOWER
            else:
                flag = TT_EXACT
            idx = f_idx[ply]
            tt_k[idx] = f_key[ply]
            tt_i[idx, 0] = d
            tt_i[idx, 1] = flag
            tt_i[idx, 2] = f_bmove[ply]
            tt_s[idx] = best
            ret = best
        else:
            ret = _eval_cached(B, H, HD, SIDE, ply, ai, P, W, PV, HB, HR, ev_key, ev_val)
        returning = True


@njit(cache=True, nogil=True)
def search_root(B, H, HD, SIDE, ai, depth, lo, hi, root_moves, n_root, out_scores, OVER, P, W, PV, HB, HR,
                tt_k, tt_i, tt_s, killers, hist, ev_key, ev_val, path, hist_keys, hist_cnt,
                stats, deadline, mbuf, max_moves):
    """ルートの全候補手を深さ depth で評価する（search.find_best_move の 1 反復分）。完了なら 1。"""
    alpha_root = lo
    for i in range(n_root):
        over = _child(B, H, HD, SIDE, 0, root_moves[i])
        OVER[1] = (SIDE[0] + 1) if over == 1 else 0
        sc = pvs(B, H, HD, SIDE, 1, ai, depth - 1, alpha_root, hi, True, OVER, P, W, PV, HB, HR,
                 tt_k, tt_i, tt_s, killers, hist, ev_key, ev_val, path, hist_keys, hist_cnt,
                 stats, deadline, mbuf, max_moves)
        if stats[1] == 1:
            return 0
        out_scores[i] = sc
        alpha_root = max(alpha_root, sc)
    return 1
