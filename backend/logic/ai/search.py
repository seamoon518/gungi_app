"""
探索エンジン (Tier 1):
  - PVS  (Principal Variation Search)    主分岐以外は零窓で高速化
  - Null Move Pruning                    局面が十分に良い場合の枝刈り
  - LMR  (Late Move Reduction)           後回しの手を浅く探索
  - History Heuristic                    Killer 拡張・手順付け精度向上
  - Aspiration Window                    反復深化で前回スコア付近に窓を絞る
  - 置換表 (TT) + 静止探索               既存から継続
"""

import copy
import time
import random
from collections import Counter
from math import inf
from typing import Dict, List, Optional, Tuple

from models.game_state import GameState
from models.piece import PieceType, Piece
from logic.movement import get_valid_moves
from logic.arata import get_valid_arata_positions
from logic.rules import (
    get_winner,
    apply_capture, apply_tsuke, apply_plain_move,
    check_boushou_defection,
)
from logic.zobrist import HASHER
from logic.ai.evaluate import evaluate, PIECE_VALUES

# ── 置換表フラグ ──────────────────────────────────────────────────────────────
TT_EXACT      = 0
TT_LOWERBOUND = 1
TT_UPPERBOUND = 2
TT_MAX_SIZE   = 300_000

MAX_KILLER_DEPTH = 16

# Null Move の削減量
_NMP_R = 2
# Aspiration Window 初期幅
_ASP_DELTA = 50


# ── データ構造 ────────────────────────────────────────────────────────────────

class TranspositionTable:
    __slots__ = ("_t",)

    def __init__(self):
        self._t: Dict[int, tuple] = {}

    def lookup(self, key: int) -> Optional[tuple]:
        return self._t.get(key)

    def store(self, key: int, depth: int, score: float, flag: int, move):
        if len(self._t) >= TT_MAX_SIZE:
            dead = list(self._t.keys())[: TT_MAX_SIZE // 5]
            for k in dead:
                del self._t[k]
        self._t[key] = (depth, score, flag, move)


class KillerMoves:
    __slots__ = ("table",)

    def __init__(self):
        self.table: List[List] = [[None, None] for _ in range(MAX_KILLER_DEPTH + 2)]

    def get(self, depth: int) -> list:
        return self.table[depth] if depth < len(self.table) else [None, None]

    def store(self, depth: int, move):
        if depth >= len(self.table):
            return
        if self.table[depth][0] != move:
            self.table[depth][1] = self.table[depth][0]
            self.table[depth][0] = move


class HistoryTable:
    """beta カット発生時に history[from][to] += depth² で更新する。"""
    __slots__ = ("_h",)

    def __init__(self):
        self._h: Dict[tuple, int] = {}

    def get(self, move: tuple) -> int:
        if move[0] != "board":
            return 0
        return self._h.get((move[1], move[2], move[3], move[4]), 0)

    def update(self, move: tuple, depth: int) -> None:
        if move[0] != "board":
            return
        key = (move[1], move[2], move[3], move[4])
        self._h[key] = min(self._h.get(key, 0) + depth * depth, 8_000)


# ── 合法手生成 ────────────────────────────────────────────────────────────────

def get_all_game_moves(state: GameState, player: str) -> list:
    moves = []
    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            if not stack or stack[-1].owner != player:
                continue
            opts = get_valid_moves(
                state.board, r, c,
                state.rules.max_stack, state.rules.sui_can_tsuke,
            )
            et_set = {(tr, tc) for tr, tc in opts.enemy_tsuke_moves}
            piece = stack[-1]
            for tr, tc in opts.valid_moves:
                dst = state.board[tr][tc]
                if dst and dst[-1].owner != player:
                    moves.append(("board", r, c, tr, tc, "capture"))
                    if (tr, tc) in et_set:
                        moves.append(("board", r, c, tr, tc, "tsuke_enemy"))
                        if piece.type == PieceType.BOU:
                            hand = state.hand_pieces.get(player, [])
                            for tidx, _ in check_boushou_defection(
                                state.board, piece, tr, tc, hand
                            ):
                                moves.append(("boushou", r, c, tr, tc, tidx))
                else:
                    moves.append(("board", r, c, tr, tc, "auto"))

    hand = state.hand_pieces.get(player, [])
    if hand:
        valid_pos = get_valid_arata_positions(state.board, player, state.rules.max_stack)
        seen: set = set()
        for p in hand:
            if p.type in seen:
                continue
            seen.add(p.type)
            for tr, tc in valid_pos:
                moves.append(("arata", p.type.value, tr, tc))
    return moves


def _get_capture_moves(state: GameState, player: str) -> list:
    moves = []
    for r in range(9):
        for c in range(9):
            stack = state.board[r][c]
            if not stack or stack[-1].owner != player:
                continue
            opts = get_valid_moves(
                state.board, r, c,
                state.rules.max_stack, state.rules.sui_can_tsuke,
            )
            for tr, tc in opts.valid_moves:
                dst = state.board[tr][tc]
                if dst and dst[-1].owner != player:
                    moves.append(("board", r, c, tr, tc, "capture"))
    return moves


# ── Move ordering ─────────────────────────────────────────────────────────────

def _order_moves(moves: list, board) -> list:
    def pri(m):
        if m[0] == "board" and m[5] == "capture":
            dst = board[m[3]][m[4]]
            if dst:
                return PIECE_VALUES.get(dst[-1].type, 0)
        return 0
    return sorted(moves, key=pri, reverse=True)


def _order_moves_full(
    moves: list, board, depth: int,
    killers: KillerMoves, history: HistoryTable,
) -> list:
    """優先度: TT手(呼び出し元で先頭挿入) > capture > killer > boushou > tsuke > history > arata > quiet"""
    kl = killers.get(depth)

    def pri(m):
        if m[0] == "board":
            if m[5] == "capture":
                dst = board[m[3]][m[4]]
                att = board[m[1]][m[2]]
                victim   = PIECE_VALUES.get(dst[-1].type, 0)   if dst else 0
                attacker = PIECE_VALUES.get(att[-1].type, 1000) if att else 1000
                return 20_000 + victim * 10 - attacker
            if m == kl[0]:          return 10_000
            if m == kl[1]:          return  9_000
            if m[5] == "tsuke_enemy": return 1_000
            return history.get(m)       # 0〜8000
        if m[0] == "boushou":       return  1_500
        if m[0] == "arata":         return    500
        return 0

    return sorted(moves, key=pri, reverse=True)


def _is_quiet(move: tuple) -> bool:
    """capture / tsuke_enemy / boushou 以外を quiet 手とみなす。"""
    if move[0] == "board":
        return move[5] not in ("capture", "tsuke_enemy")
    if move[0] == "boushou":
        return False
    return True  # arata は quiet 扱い


# ── 状態コピー + インプレース適用 ─────────────────────────────────────────────

def _make_search_copy(state: GameState) -> GameState:
    return GameState(
        board=copy.deepcopy(state.board),
        current_player=state.current_player,
        hand_pieces={k: list(v) for k, v in state.hand_pieces.items()},
        game_over=state.game_over,
        winner=state.winner,
        level=state.level,
        mode=state.mode,
        ai_difficulty=state.ai_difficulty,
        ai_player=state.ai_player,
        phase=state.phase,
        setup_done=dict(state.setup_done),
        rules=state.rules,
    )


def _make_null_move(state: GameState) -> GameState:
    """手を指さず手番だけ切り替える（Null Move 用）。"""
    ns = _make_search_copy(state)
    ns.current_player = "white" if state.current_player == "black" else "black"
    return ns


def _apply_move_inplace(ns: GameState, move: tuple) -> bool:
    player = ns.current_player

    if move[0] == "board":
        _, fr, fc, tr, tc, action = move
        src = ns.board[fr][fc]
        if not src or src[-1].owner != player:
            return False
        piece = src[-1]
        dst = ns.board[tr][tc]
        if action == "tsuke_enemy":
            apply_tsuke(ns.board, piece, fr, fc, tr, tc)
        elif dst and dst[-1].owner != player:
            apply_capture(ns.board, piece, fr, fc, tr, tc)
        elif dst and dst[-1].owner == player:
            apply_tsuke(ns.board, piece, fr, fc, tr, tc)
        else:
            apply_plain_move(ns.board, piece, fr, fc, tr, tc)

    elif move[0] == "arata":
        _, pt_str, tr, tc = move
        try:
            pt = PieceType(pt_str)
        except ValueError:
            return False
        hand = ns.hand_pieces.get(player, [])
        idx = next((i for i, p in enumerate(hand) if p.type == pt), None)
        if idx is None:
            return False
        piece = hand.pop(idx)
        ns.board[tr][tc].append(piece)

    elif move[0] == "boushou":
        _, fr, fc, tr, tc, target_index = move
        src = ns.board[fr][fc]
        if not src or src[-1].owner != player or src[-1].type != PieceType.BOU:
            return False
        dst = ns.board[tr][tc]
        if not dst or target_index < 0 or target_index >= len(dst):
            return False
        target_piece = dst[target_index]
        enemy = "white" if player == "black" else "black"
        if target_piece.owner != enemy:
            return False
        hand = ns.hand_pieces.get(player, [])
        hand_idx = next((i for i, p in enumerate(hand) if p.type == target_piece.type), None)
        if hand_idx is None:
            return False
        bou_piece = src.pop()
        own_piece = hand.pop(hand_idx)
        dst.pop(target_index)
        dst.insert(target_index, own_piece)
        dst.append(bou_piece)

    else:
        return False

    winner = get_winner(ns.board)
    if winner:
        ns.game_over = True
        ns.winner = winner
    ns.current_player = "white" if player == "black" else "black"
    return True


# ── 局面キー ──────────────────────────────────────────────────────────────────

def _state_key(state: GameState) -> int:
    return HASHER.hash_state(state)


# ── 静止探索 ──────────────────────────────────────────────────────────────────

def quiescence(
    state: GameState,
    ai_player: str,
    alpha: float,
    beta: float,
    start_time: float,
    time_limit: float,
    qdepth: int = 2,
    weights: Optional[dict] = None,
) -> float:
    if time.time() - start_time > time_limit:
        raise TimeoutError()

    stand_pat = evaluate(state, ai_player, weights)
    maximizing = (state.current_player == ai_player)

    if maximizing:
        if stand_pat >= beta:
            return beta
        alpha = max(alpha, stand_pat)
    else:
        if stand_pat <= alpha:
            return alpha
        beta = min(beta, stand_pat)

    if qdepth == 0:
        return stand_pat

    winner = get_winner(state.board)
    if winner:
        return 90_000 if winner == ai_player else -90_000

    captures = _get_capture_moves(state, state.current_player)
    captures = _order_moves(captures, state.board)

    for move in captures:
        ns = _make_search_copy(state)
        if not _apply_move_inplace(ns, move):
            continue
        v = quiescence(ns, ai_player, alpha, beta, start_time, time_limit, qdepth - 1, weights)
        if maximizing:
            if v >= beta:
                return beta
            alpha = max(alpha, v)
        else:
            if v <= alpha:
                return alpha
            beta = min(beta, v)

    return alpha if maximizing else beta


# ── PVS（Principal Variation Search） ────────────────────────────────────────

def pvs(
    state: GameState,
    ai_player: str,
    depth: int,
    alpha: float,
    beta: float,
    start_time: float,
    time_limit: float,
    max_moves: int,
    tt: TranspositionTable,
    killers: KillerMoves,
    history: HistoryTable,
    weights: Optional[dict] = None,
    null_move_allowed: bool = True,
    position_counter: Optional[Counter] = None,
) -> float:

    if time.time() - start_time > time_limit:
        raise TimeoutError()

    key = _state_key(state)

    # ── 千日手回避: この局面が実ゲームで 3回以上登場 → 次に戻ると千日手 ─────
    if position_counter and position_counter.get(key, 0) >= 3:
        return 0

    # ── TT lookup ────────────────────────────────────────────────────────────
    entry = tt.lookup(key)
    if entry and entry[0] >= depth:
        tt_depth, tt_score, tt_flag, tt_move = entry
        if tt_flag == TT_EXACT:
            return tt_score
        if tt_flag == TT_LOWERBOUND:
            alpha = max(alpha, tt_score)
        elif tt_flag == TT_UPPERBOUND:
            beta = min(beta, tt_score)
        if alpha >= beta:
            return tt_score

    # ── 終局判定 ─────────────────────────────────────────────────────────────
    if state.game_over:
        return (100_000 + depth) if state.winner == ai_player else (-100_000 - depth)
    winner = get_winner(state.board)
    if winner:
        return (100_000 + depth) if winner == ai_player else (-100_000 - depth)

    # ── 葉ノード ─────────────────────────────────────────────────────────────
    if depth == 0:
        return quiescence(state, ai_player, alpha, beta, start_time, time_limit, weights=weights)

    current    = state.current_player
    maximizing = (current == ai_player)

    # ── Null Move Pruning（最大化側のみ） ─────────────────────────────────────
    if (null_move_allowed
            and depth >= _NMP_R + 1
            and maximizing
            and not state.game_over):
        static_eval = evaluate(state, ai_player, weights)
        if static_eval >= beta:
            null_state = _make_null_move(state)
            null_score = pvs(
                null_state, ai_player, depth - 1 - _NMP_R,
                beta - 1, beta,
                start_time, time_limit, max_moves,
                tt, killers, history, weights,
                null_move_allowed=False,
                position_counter=position_counter,
            )
            if null_score >= beta:
                return beta   # null move cutoff

    # ── 合法手生成 + move ordering ───────────────────────────────────────────
    moves = get_all_game_moves(state, current)
    if not moves:
        return evaluate(state, ai_player, weights)

    tt_first = entry[3] if (entry and entry[3] in moves) else None
    moves = _order_moves_full(moves, state.board, depth, killers, history)
    if tt_first and tt_first in moves:
        moves.remove(tt_first)
        moves.insert(0, tt_first)

    if len(moves) > max_moves:
        moves = moves[:max_moves]

    best_score = -inf if maximizing else inf
    best_move  = None
    orig_alpha = alpha

    for i, move in enumerate(moves):
        ns = _make_search_copy(state)
        if not _apply_move_inplace(ns, move):
            continue

        # LMR: 後回しの quiet 手は 1 層浅く探索
        reduction = (1
                     if (depth >= 3 and i >= 4 and _is_quiet(move))
                     else 0)

        _pc = position_counter  # 短縮エイリアス
        if i == 0:
            # ── 主分岐: フルウィンドウ ─────────────────────────────────────
            v = pvs(ns, ai_player, depth - 1, alpha, beta,
                    start_time, time_limit, max_moves,
                    tt, killers, history, weights,
                    position_counter=_pc)
        else:
            if maximizing:
                # ── 零窓 + LMR ────────────────────────────────────────────
                v = pvs(ns, ai_player, depth - 1 - reduction, alpha, alpha + 1,
                        start_time, time_limit, max_moves,
                        tt, killers, history, weights,
                        position_counter=_pc)
                # LMR fail-high → フル深さで零窓再探索
                if v > alpha and reduction > 0:
                    v = pvs(ns, ai_player, depth - 1, alpha, alpha + 1,
                            start_time, time_limit, max_moves,
                            tt, killers, history, weights,
                            position_counter=_pc)
                # 零窓 fail-high → フルウィンドウ再探索
                if v > alpha and v < beta:
                    v = pvs(ns, ai_player, depth - 1, alpha, beta,
                            start_time, time_limit, max_moves,
                            tt, killers, history, weights,
                            position_counter=_pc)
            else:
                # ── 最小化側 ──────────────────────────────────────────────
                v = pvs(ns, ai_player, depth - 1 - reduction, beta - 1, beta,
                        start_time, time_limit, max_moves,
                        tt, killers, history, weights,
                        position_counter=_pc)
                if v < beta and reduction > 0:
                    v = pvs(ns, ai_player, depth - 1, beta - 1, beta,
                            start_time, time_limit, max_moves,
                            tt, killers, history, weights,
                            position_counter=_pc)
                if v < beta and v > alpha:
                    v = pvs(ns, ai_player, depth - 1, alpha, beta,
                            start_time, time_limit, max_moves,
                            tt, killers, history, weights,
                            position_counter=_pc)

        # ── スコア更新 ───────────────────────────────────────────────────────
        if maximizing:
            if v > best_score:
                best_score = v
                best_move  = move
            alpha = max(alpha, best_score)
        else:
            if v < best_score:
                best_score = v
                best_move  = move
            beta = min(beta, best_score)

        if alpha >= beta:
            # beta cutoff: killer + history に登録
            if _is_quiet(move):
                killers.store(depth, move)
                history.update(move, depth)
            break

    # ── TT store ─────────────────────────────────────────────────────────────
    if best_move is not None:
        flag = (TT_UPPERBOUND if best_score <= orig_alpha
                else TT_LOWERBOUND if best_score >= beta
                else TT_EXACT)
        tt.store(key, depth, best_score, flag, best_move)

    fallback = evaluate(state, ai_player, weights)
    if maximizing:
        return best_score if best_score > -inf else fallback
    return best_score if best_score < inf else fallback


# ── メインエントリポイント ────────────────────────────────────────────────────

def find_best_move(
    state: GameState,
    ai_player: str,
    max_depth: int,
    time_limit: float,
    noise: int = 0,
    max_moves: int = 25,
    weights: Optional[dict] = None,
) -> Optional[tuple]:
    """
    反復深化 + PVS + Aspiration Window で最善手を返す。
    時間切れ時は直前の深さの結果を使用。
    """
    moves = get_all_game_moves(state, ai_player)
    if not moves:
        return None

    moves = _order_moves(moves, state.board)
    start_time = time.time()

    best_move: Optional[tuple] = None
    for m in moves:
        ns = _make_search_copy(state)
        if _apply_move_inplace(ns, m):
            best_move = m
            break
    if best_move is None:
        return None

    tt      = TranspositionTable()
    killers = KillerMoves()
    history = HistoryTable()

    # 実ゲームの局面出現回数を O(1) で参照できるように Counter 化
    position_counter: Counter = Counter(state.position_history)

    prev_score = 0

    for depth in range(1, max_depth + 1):
        asp_delta = _ASP_DELTA
        # depth 1 はフルウィンドウ、それ以降は aspiration
        lo: float = -inf if depth == 1 else prev_score - asp_delta
        hi: float =  inf if depth == 1 else prev_score + asp_delta

        scored_this_depth: Optional[List[Tuple[float, tuple]]] = None

        try:
            for attempt in range(4):   # 最大 3 回拡大 → 4 回目はフルウィンドウ
                if attempt == 3:
                    lo, hi = -inf, inf

                current_scored: List[Tuple[float, tuple]] = []
                alpha_root = lo

                for move in moves:
                    ns = _make_search_copy(state)
                    if not _apply_move_inplace(ns, move):
                        continue
                    score = pvs(
                        ns, ai_player, depth - 1,
                        alpha_root, hi,
                        start_time, time_limit, max_moves,
                        tt, killers, history, weights,
                        position_counter=position_counter,
                    )
                    current_scored.append((score, move))
                    alpha_root = max(alpha_root, score)

                if not current_scored:
                    break

                best_s = max(s for s, _ in current_scored)

                # Aspiration window 判定（depth > 1 のみ）
                if depth > 1 and attempt < 3:
                    if best_s <= lo:
                        asp_delta *= 2
                        lo = prev_score - asp_delta
                        continue   # fail-low: 下限を広げて再探索
                    if best_s >= hi:
                        asp_delta *= 2
                        hi = prev_score + asp_delta
                        continue   # fail-high: 上限を広げて再探索

                # 成功 or フルウィンドウ
                scored_this_depth = current_scored
                prev_score = best_s
                break

        except TimeoutError:
            pass  # 時間切れ: scored_this_depth が None のまま → 前の深さの結果を使う

        if scored_this_depth is None:
            break  # このdepthは完了しなかった

        # best_move を更新
        scored_this_depth.sort(key=lambda x: x[0], reverse=True)
        top_score = scored_this_depth[0][0]

        if noise > 0:
            candidates = [m for s, m in scored_this_depth if s >= top_score - noise]
            best_move = random.choice(candidates)
        else:
            best_move = scored_this_depth[0][1]

        # 次の深さのためにmove順を更新
        if best_move in moves:
            moves = [best_move] + [m for m in moves if m != best_move]

    return best_move
