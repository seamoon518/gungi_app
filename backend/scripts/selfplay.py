"""
selfplay.py: 2つの AI 設定間で1局を実行し、棋譜 dict を返す。

使用例:
    from scripts.selfplay import play_game
    record = play_game(
        ai_a_config={"weights": "tier0", "max_depth": 6, "time_limit": 5.0, "noise": 0, "max_moves": 15},
        ai_b_config={"weights": "tier0", "max_depth": 6, "time_limit": 5.0, "noise": 0, "max_moves": 15},
        level="joukyuu",
    )
"""

import time
import uuid
from typing import Optional

from logic.game_engine import (
    create_initial_state, apply_move, apply_arata, apply_boushou,
)
from logic.ai.engine import _handle_setup
from logic.ai.search import find_best_move
from logic.ai.weights import load_weights


_DEFAULT_CONFIG = {
    "weights": "tier1",
    "max_depth": 12,
    "time_limit": 5.0,
    "noise": 0,
    "max_moves": 15,
}


def play_game(
    ai_a_config: dict,
    ai_b_config: dict,
    level: str = "joukyuu",
    max_moves: int = 300,
    time_limit: Optional[float] = None,
    black_is_a: bool = True,
) -> dict:
    """
    1局を実行する。ai_a が黒（先手）、ai_b が白（後手）。
    black_is_a=False の場合は ai_a が白、ai_b が黒になる。

    Parameters
    ----------
    ai_a_config : dict
        keys: weights, max_depth, time_limit, noise, max_moves
    ai_b_config : dict
        同上
    level : str
        ゲームレベル（nyumon / shokyuu / chukyuu / joukyuu）
    max_moves : int
        手数上限（超えたら引き分け）
    time_limit : float | None
        None の場合は各 config の time_limit を使用
    black_is_a : bool
        True: ai_a=黒, ai_b=白 / False: ai_a=白, ai_b=黒

    Returns
    -------
    dict
        棋譜 JSON スキーマ準拠の dict
    """
    cfg_a = {**_DEFAULT_CONFIG, **ai_a_config}
    cfg_b = {**_DEFAULT_CONFIG, **ai_b_config}

    black_cfg = cfg_a if black_is_a else cfg_b
    white_cfg = cfg_b if black_is_a else cfg_a

    game_id = str(uuid.uuid4())
    state = create_initial_state(level=level, mode="ai", ai_difficulty="hard")
    state.ai_player = "white"  # create_initial_state デフォルトに合わせる

    moves_log = []
    move_count = 0
    reached_depth_sum = 0
    reached_depth_count = 0

    # ── setup フェーズ（chukyuu / joukyuu） ──────────────────────────────────
    if state.phase == "setup":
        setup_steps = 0
        while state.phase == "setup" and setup_steps < 200:
            current = state.current_player
            state.ai_player = current
            ok, err = _handle_setup(state, current)
            if not ok:
                break
            setup_steps += 1

    # ── ゲームフェーズ ────────────────────────────────────────────────────────
    while not state.game_over and move_count < max_moves:
        current = state.current_player
        cfg = black_cfg if current == "black" else white_cfg

        weights = load_weights(cfg["weights"])
        tl = time_limit if time_limit is not None else cfg["time_limit"]

        t0 = time.time()
        best = find_best_move(
            state,
            current,
            max_depth=cfg["max_depth"],
            time_limit=tl,
            noise=cfg["noise"],
            max_moves=cfg["max_moves"],
            weights=weights,
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        if best is None:
            state.game_over = True
            state.winner = "white" if current == "black" else "black"
            break

        move_entry: dict = {
            "player": current,
            "type": best[0],
            "time_ms": elapsed_ms,
        }

        if best[0] == "board":
            _, fr, fc, tr, tc, action = best
            move_entry.update({"from": [fr, fc], "to": [tr, tc], "action": action})
            ok, _ = apply_move(state, fr, fc, tr, tc, action)
        elif best[0] == "arata":
            _, pt_str, tr, tc = best
            move_entry.update({"to": [tr, tc], "piece": pt_str})
            ok, _ = apply_arata(state, pt_str, tr, tc)
        elif best[0] == "boushou":
            _, fr, fc, tr, tc, target_index = best
            move_entry.update({"from": [fr, fc], "to": [tr, tc], "target_index": target_index})
            ok, _ = apply_boushou(state, fr, fc, tr, tc, target_index)
        else:
            break

        if not ok:
            state.game_over = True
            state.winner = "white" if current == "black" else "black"
            break

        moves_log.append(move_entry)
        move_count += 1

    # ── 結果集計 ──────────────────────────────────────────────────────────────
    if state.game_over and state.winner == "black":
        result = "ai_a_win" if black_is_a else "ai_b_win"
        winner = "black"
        termination = "sui_captured"
    elif state.game_over and state.winner == "white":
        result = "ai_b_win" if black_is_a else "ai_a_win"
        winner = "white"
        termination = "sui_captured"
    elif state.game_over and state.winner is None:
        result = "draw"
        winner = None
        termination = "sennichite"
    else:
        result = "draw"
        winner = None
        termination = "max_moves"

    avg_time = (
        int(sum(m["time_ms"] for m in moves_log) / len(moves_log))
        if moves_log else 0
    )

    return {
        "game_id": game_id,
        "ai_a": cfg_a["weights"],
        "ai_b": cfg_b["weights"],
        "level": level,
        "moves": moves_log,
        "result": result,
        "winner": winner,
        "termination": termination,
        "total_moves": move_count,
        "avg_thinking_time_ms": avg_time,
    }
