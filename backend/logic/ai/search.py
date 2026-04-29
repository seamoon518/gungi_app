"""
Phase E alpha-beta 探索:
  - 置換表 (Transposition Table) : 同一局面の再探索を防ぐ
  - 静止探索 (Quiescence Search)  : 地平線効果を軽減
  - Killer Heuristic              : 枝刈りを増やすmove ordering
  - MVV-LVA move ordering         : 高価値の取り手を優先
  - 反復深化 + 時間制御            : 指定時間内で最善手を返す
"""

import copy
import time
import random
from math import inf
from typing import Dict, List, Optional, Tuple

from models.game_state import GameState
from models.piece import PieceType, Piece
from logic.movement import get_valid_moves
from logic.arata import get_valid_arata_positions
from logic.rules import get_winner, board_hash, apply_capture, apply_tsuke, apply_plain_move
from logic.ai.evaluate import evaluate, PIECE_VALUES

# ── 置換表フラグ ──────────────────────────────────────────────────────────────
TT_EXACT      = 0
TT_LOWERBOUND = 1  # fail-high (beta cutoff)
TT_UPPERBOUND = 2  # fail-low  (alpha cutoff)
TT_MAX_SIZE   = 300_000

MAX_KILLER_DEPTH = 12


# ── データ構造 ────────────────────────────────────────────────────────────────

class TranspositionTable:
    """置換表: 局面ハッシュ → (depth, score, flag, best_move)"""
    __slots__ = ("_t",)

    def __init__(self):
        self._t: Dict[str, tuple] = {}

    def lookup(self, key: str) -> Optional[tuple]:
        return self._t.get(key)

    def store(self, key: str, depth: int, score: float, flag: int, move):
        if len(self._t) >= TT_MAX_SIZE:
            # 古いエントリを20%削除
            dead = list(self._t.keys())[: TT_MAX_SIZE // 5]
            for k in dead:
                del self._t[k]
        self._t[key] = (depth, score, flag, move)


class KillerMoves:
    """各深さで beta cutoff を引き起こした手を2つ保持"""
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


# ── 合法手生成 ────────────────────────────────────────────────────────────────

def get_all_game_moves(state: GameState, player: str) -> list:
    """指定プレイヤーの全合法手を生成する（ゲームフェーズ用）"""
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
            for tr, tc in opts.valid_moves:
                dst = state.board[tr][tc]
                if dst and dst[-1].owner != player:
                    moves.append(('board', r, c, tr, tc, 'capture'))
                    if (tr, tc) in et_set:
                        moves.append(('board', r, c, tr, tc, 'tsuke_enemy'))
                else:
                    moves.append(('board', r, c, tr, tc, 'auto'))

    hand = state.hand_pieces.get(player, [])
    if hand:
        valid_pos = get_valid_arata_positions(state.board, player, state.rules.max_stack)
        seen: set = set()
        for p in hand:
            if p.type in seen:
                continue
            seen.add(p.type)
            for tr, tc in valid_pos:
                moves.append(('arata', p.type.value, tr, tc))
    return moves


def _get_capture_moves(state: GameState, player: str) -> list:
    """静止探索用: 捕獲手のみ生成"""
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
                    moves.append(('board', r, c, tr, tc, 'capture'))
    return moves


# ── Move ordering ─────────────────────────────────────────────────────────────

def _order_moves(moves: list, board) -> list:
    """基本 move ordering: MVV-LVA（キャプチャを価値順）"""
    def pri(m):
        if m[0] == 'board' and m[5] == 'capture':
            dst = board[m[3]][m[4]]
            if dst:
                return PIECE_VALUES.get(dst[-1].type, 0)
        return 0
    return sorted(moves, key=pri, reverse=True)


def _order_moves_full(moves: list, board, depth: int, killers: KillerMoves) -> list:
    """強化 move ordering: MVV-LVA > killer > tsuke_enemy > arata > その他"""
    kl = killers.get(depth)

    def pri(m):
        if m[0] == 'board':
            if m[5] == 'capture':
                dst = board[m[3]][m[4]]
                att = board[m[1]][m[2]]
                victim = PIECE_VALUES.get(dst[-1].type, 0) if dst else 0
                attacker = PIECE_VALUES.get(att[-1].type, 1000) if att else 1000
                return 20_000 + victim * 10 - attacker  # MVV-LVA
            if m == kl[0]:
                return 10_000
            if m == kl[1]:
                return 9_000
            if m[5] == 'tsuke_enemy':
                return 1_000
        if m[0] == 'arata':
            return 500
        return 0

    return sorted(moves, key=pri, reverse=True)


# ── 状態コピー + インプレース適用 ─────────────────────────────────────────────

def _make_search_copy(state: GameState) -> GameState:
    """高速コピー: move_history/position_history をスキップ"""
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


def _apply_move_inplace(ns: GameState, move: tuple) -> bool:
    """サーチコピーに move をインプレース適用（rules.py 直呼び）"""
    player = ns.current_player

    if move[0] == 'board':
        _, fr, fc, tr, tc, action = move
        src = ns.board[fr][fc]
        if not src or src[-1].owner != player:
            return False
        piece = src[-1]
        dst = ns.board[tr][tc]

        if action == 'tsuke_enemy':
            apply_tsuke(ns.board, piece, fr, fc, tr, tc)
        elif dst and dst[-1].owner != player:
            apply_capture(ns.board, piece, fr, fc, tr, tc)
        elif dst and dst[-1].owner == player:
            apply_tsuke(ns.board, piece, fr, fc, tr, tc)
        else:
            apply_plain_move(ns.board, piece, fr, fc, tr, tc)

    elif move[0] == 'arata':
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
    else:
        return False

    winner = get_winner(ns.board)
    if winner:
        ns.game_over = True
        ns.winner = winner
    ns.current_player = "white" if player == "black" else "black"
    return True


# ── 局面キー（置換表用） ──────────────────────────────────────────────────────

def _state_key(state: GameState) -> str:
    bh = board_hash(state.board)
    bk = ",".join(sorted(p.type.value for p in state.hand_pieces.get("black", [])))
    wh = ",".join(sorted(p.type.value for p in state.hand_pieces.get("white", [])))
    return f"{bh}|{state.current_player}|{bk}|{wh}"


# ── 静止探索 (quiescence search) ─────────────────────────────────────────────

def quiescence(
    state: GameState,
    ai_player: str,
    alpha: float,
    beta: float,
    start_time: float,
    time_limit: float,
    qdepth: int = 2,
) -> float:
    """
    捕獲手のみを追加探索して水平線効果を軽減。
    qdepth: 最大追加深さ（2 が推奨）
    """
    if time.time() - start_time > time_limit:
        raise TimeoutError()

    stand_pat = evaluate(state, ai_player)
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
        return (90_000) if winner == ai_player else (-90_000)

    captures = _get_capture_moves(state, state.current_player)
    captures = _order_moves(captures, state.board)

    for move in captures:
        ns = _make_search_copy(state)
        if not _apply_move_inplace(ns, move):
            continue
        v = quiescence(ns, ai_player, alpha, beta, start_time, time_limit, qdepth - 1)
        if maximizing:
            if v >= beta:
                return beta
            alpha = max(alpha, v)
        else:
            if v <= alpha:
                return alpha
            beta = min(beta, v)

    return alpha if maximizing else beta


# ── Minimax with TT + Killers ─────────────────────────────────────────────────

def minimax(
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
) -> float:
    if time.time() - start_time > time_limit:
        raise TimeoutError()

    # ── 置換表 lookup ──────────────────────────────────────────────────────────
    key = _state_key(state)
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

    # ── 終局判定 ───────────────────────────────────────────────────────────────
    if state.game_over:
        return (100_000 + depth) if state.winner == ai_player else (-100_000 - depth)
    winner = get_winner(state.board)
    if winner:
        return (100_000 + depth) if winner == ai_player else (-100_000 - depth)

    # ── 葉ノード: 静止探索 ─────────────────────────────────────────────────────
    if depth == 0:
        return quiescence(state, ai_player, alpha, beta, start_time, time_limit)

    # ── 合法手生成 + move ordering ─────────────────────────────────────────────
    current = state.current_player
    moves = get_all_game_moves(state, current)
    if not moves:
        return evaluate(state, ai_player)

    # 置換表の best_move を先頭に
    tt_first = entry[3] if (entry and entry[3] in moves) else None
    moves = _order_moves_full(moves, state.board, depth, killers)
    if tt_first and tt_first in moves:
        moves.remove(tt_first)
        moves.insert(0, tt_first)

    if len(moves) > max_moves:
        moves = moves[:max_moves]

    maximizing = (current == ai_player)
    best_score = -inf if maximizing else inf
    best_move = None
    orig_alpha = alpha

    for move in moves:
        ns = _make_search_copy(state)
        if not _apply_move_inplace(ns, move):
            continue

        v = minimax(ns, ai_player, depth - 1, alpha, beta,
                    start_time, time_limit, max_moves, tt, killers)

        if maximizing:
            if v > best_score:
                best_score = v
                best_move = move
            alpha = max(alpha, best_score)
        else:
            if v < best_score:
                best_score = v
                best_move = move
            beta = min(beta, best_score)

        if alpha >= beta:
            # Beta cutoff: killer に登録（取り手以外）
            if not (move[0] == 'board' and state.board[move[3]][move[4]]):
                killers.store(depth, move)
            break

    # ── 置換表 store ───────────────────────────────────────────────────────────
    if best_move is not None:
        if best_score <= orig_alpha:
            flag = TT_UPPERBOUND
        elif best_score >= beta:
            flag = TT_LOWERBOUND
        else:
            flag = TT_EXACT
        tt.store(key, depth, best_score, flag, best_move)

    fallback = evaluate(state, ai_player)
    if maximizing:
        return best_score if best_score > -inf else fallback
    else:
        return best_score if best_score < inf else fallback


# ── メインエントリポイント ────────────────────────────────────────────────────

def find_best_move(
    state: GameState,
    ai_player: str,
    max_depth: int,
    time_limit: float,
    noise: int = 0,
    max_moves: int = 25,
) -> Optional[tuple]:
    """
    反復深化 + 置換表 + killer heuristic で最善手を返す。
    時間切れ時は直前の深さの結果を使用。
    """
    moves = get_all_game_moves(state, ai_player)
    if not moves:
        return None

    moves = _order_moves(moves, state.board)
    start_time = time.time()

    # 確実に有効なフォールバック手を確保
    best_move: Optional[tuple] = None
    for m in moves:
        ns = _make_search_copy(state)
        if _apply_move_inplace(ns, m):
            best_move = m
            break
    if best_move is None:
        return None

    tt = TranspositionTable()
    killers = KillerMoves()

    for depth in range(1, max_depth + 1):
        try:
            scored: List[Tuple[float, tuple]] = []
            alpha = -inf

            for move in moves:
                ns = _make_search_copy(state)
                if not _apply_move_inplace(ns, move):
                    continue
                score = minimax(
                    ns, ai_player, depth - 1,
                    alpha, inf,
                    start_time, time_limit, max_moves, tt, killers,
                )
                scored.append((score, move))
                alpha = max(alpha, score)

        except TimeoutError:
            break

        if not scored:
            continue

        scored.sort(key=lambda x: x[0], reverse=True)
        top_score = scored[0][0]

        if noise > 0:
            candidates = [m for s, m in scored if s >= top_score - noise]
            best_move = random.choice(candidates)
        else:
            best_move = scored[0][1]

        # 次の深さのためにmove順を更新（best_moveを先頭に）
        if best_move in moves:
            moves = [best_move] + [m for m in moves if m != best_move]

    return best_move
