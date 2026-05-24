"""
Phase 1: 自己対戦でポジションデータを収集する。

Usage:
    python -m scripts.generate_positions \\
        --hours 4 --parallel 4 --level joukyuu --out data/tuning/positions.pkl
"""

import argparse
import pathlib
import pickle
import sys
import time
from multiprocessing import Pool


def _fix_path():
    p = str(pathlib.Path(__file__).parent.parent.absolute())
    if p not in sys.path:
        sys.path.insert(0, p)


_fix_path()


# ── シリアライズ ──────────────────────────────────────────────────────────────

def serialize_state(state) -> dict:
    """評価に必要な最小情報のみを dict に変換する。"""
    return {
        "board": [
            [[{"t": p.type.value, "o": p.owner[0]} for p in stack]
             for stack in row]
            for row in state.board
        ],
        "hand_b": [p.type.value for p in state.hand_pieces.get("black", [])],
        "hand_w": [p.type.value for p in state.hand_pieces.get("white", [])],
    }


def deserialize_state(data: dict):
    """evaluate() が使える最小オブジェクトに復元する。"""
    _fix_path()
    from types import SimpleNamespace
    from models.piece import Piece, PieceType

    owner_map = {"b": "black", "w": "white"}
    board = [
        [
            [Piece(PieceType(p["t"]), owner_map[p["o"]]) for p in stack]
            for stack in row
        ]
        for row in data["board"]
    ]
    hand_pieces = {
        "black": [Piece(PieceType(t), "black") for t in data["hand_b"]],
        "white": [Piece(PieceType(t), "white") for t in data["hand_w"]],
    }
    return SimpleNamespace(board=board, hand_pieces=hand_pieces)


# ── ワーカー（マルチプロセス） ────────────────────────────────────────────────

def _play_and_collect(args: tuple) -> list:
    """
    1局を実行してポジションリストを返す。
    戻り値: [(serialized_state_dict, result_float), ...]
      result: 白勝=1.0, 引分=0.5, 黒勝=0.0
    """
    level, time_limit, max_moves, sample_rate = args

    _fix_path()

    from models.game_state import GameRules, RULES_BY_LEVEL
    from logic.game_engine import (
        create_initial_state, apply_move, apply_arata, apply_boushou,
    )
    from logic.ai.engine import _handle_setup
    from logic.ai.search import find_best_move
    from logic.ai.weights import load_weights

    weights = load_weights("tier1")
    state = create_initial_state(level=level, mode="ai", ai_difficulty="hard")
    state.ai_player = "white"

    # ── setup フェーズ（chukyuu / joukyuu） ──────────────────────────────────
    if state.phase == "setup":
        for _ in range(200):
            if state.phase != "setup":
                break
            current = state.current_player
            state.ai_player = current
            ok, _ = _handle_setup(state, current)
            if not ok:
                break

    # ── game フェーズ ─────────────────────────────────────────────────────────
    positions_raw = []
    move_count = 0

    while not state.game_over and move_count < max_moves:
        current = state.current_player

        # 3手に1回サンプリング
        if move_count % sample_rate == 0:
            positions_raw.append(serialize_state(state))

        best = find_best_move(
            state, current,
            max_depth=12,
            time_limit=time_limit,
            noise=10,       # 多様な局面を生成するため少しノイズ
            max_moves=15,
            weights=weights,
        )

        if best is None:
            state.game_over = True
            state.winner = "white" if current == "black" else "black"
            break

        ok = False
        if best[0] == "board":
            ok, _ = apply_move(state, best[1], best[2], best[3], best[4], best[5])
        elif best[0] == "arata":
            ok, _ = apply_arata(state, best[1], best[2], best[3])
        elif best[0] == "boushou":
            ok, _ = apply_boushou(state, best[1], best[2], best[3], best[4], best[5])

        if not ok:
            break
        move_count += 1

    # ── 結果タグ付け（白視点） ────────────────────────────────────────────────
    if state.game_over and state.winner == "white":
        result = 1.0
    elif state.game_over and state.winner == "black":
        result = 0.0
    else:
        result = 0.5

    return [(pos, result) for pos in positions_raw]


# ── メイン ────────────────────────────────────────────────────────────────────

def generate(
    out_path: str = "data/tuning/positions.pkl",
    level: str = "joukyuu",
    time_budget_hours: float = 4.0,
    parallel: int = 4,
    move_time_limit: float = 1.0,
    max_moves: int = 300,
    sample_rate: int = 3,
) -> int:
    """
    自己対戦を time_budget_hours 時間走らせてポジションを収集する。
    Returns: 収集したポジション数
    """
    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # ゲーム数の事前見積もり（joukyuu: setup~5s + game~70s = ~75s/局）
    est_secs_per_game = 75
    total_worker_secs = time_budget_hours * 3600 * parallel
    est_games = max(int(total_worker_secs / est_secs_per_game), 8)

    tasks = [
        (level, move_time_limit, max_moves, sample_rate)
        for _ in range(est_games)
    ]

    print(f"[gen] level={level}  tl={move_time_limit}s/手  "
          f"parallel={parallel}  budget={time_budget_hours}h  "
          f"est_games={est_games}", flush=True)

    all_positions = []
    deadline = time.time() + time_budget_hours * 3600
    game_count = 0
    start = time.time()

    with Pool(processes=parallel) as pool:
        for game_positions in pool.imap_unordered(_play_and_collect, tasks):
            all_positions.extend(game_positions)
            game_count += 1

            if game_count % 10 == 0 or game_count <= 5:
                elapsed = time.time() - start
                remaining = max(0, deadline - time.time())
                print(f"  games={game_count:4d}  positions={len(all_positions):6d}"
                      f"  elapsed={elapsed/3600:.2f}h  remaining={remaining/3600:.2f}h",
                      flush=True)

            if time.time() >= deadline:
                print("[gen] time budget reached, stopping.", flush=True)
                pool.terminate()
                break

    with open(out, "wb") as f:
        pickle.dump(all_positions, f)

    print(f"[gen] done  games={game_count}  positions={len(all_positions)}"
          f"  saved={out}", flush=True)
    return len(all_positions)


def main():
    parser = argparse.ArgumentParser(description="自己対戦ポジション生成")
    parser.add_argument("--hours",    type=float, default=4.0)
    parser.add_argument("--parallel", type=int,   default=4)
    parser.add_argument("--level",    default="joukyuu")
    parser.add_argument("--tl",       type=float, default=1.0, dest="time_limit")
    parser.add_argument("--out",      default="data/tuning/positions.pkl")
    args = parser.parse_args()

    generate(
        out_path=args.out,
        level=args.level,
        time_budget_hours=args.hours,
        parallel=args.parallel,
        move_time_limit=args.time_limit,
    )


if __name__ == "__main__":
    main()
