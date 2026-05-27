"""
蒸留用ポジション生成。

従来の generate_positions.py との違い:
  - ゲーム結果（勝/負/引分）を使わない
  - 各局面で pvs_score（探索の評価値）を白視点で記録する
  - 引き分けでも全局面が有効なデータになる → 引き分け問題ゼロ

Usage:
    python -m scripts.generate_positions_distill \\
        --hours 8 --parallel 4 --level joukyuu \\
        --out data/tuning/distill_positions.pkl
"""

import argparse
import pathlib
import pickle
import sys
import time
from multiprocessing import Pool

_SCORE_CLIP = 3000  # pvs スコアをこの範囲にクリップ（外れ値を抑制）


def _fix_path():
    p = str(pathlib.Path(__file__).parent.parent.absolute())
    if p not in sys.path:
        sys.path.insert(0, p)


_fix_path()


def serialize_state(state) -> dict:
    return {
        "board": [
            [[{"t": p.type.value, "o": p.owner[0]} for p in stack]
             for stack in row]
            for row in state.board
        ],
        "hand_b": [p.type.value for p in state.hand_pieces.get("black", [])],
        "hand_w": [p.type.value for p in state.hand_pieces.get("white", [])],
    }


def _play_and_collect(args: tuple) -> list:
    """
    1局を実行して (serialized_state, pvs_score_from_white) のリストを返す。
    pvs_score は探索で得た評価値（白視点）。静的評価より正確な教師信号。
    """
    level, time_limit, max_moves, sample_rate = args

    _fix_path()
    from logic.game_engine import (
        create_initial_state, apply_move, apply_arata, apply_boushou,
    )
    from logic.ai.engine import _handle_setup
    from logic.ai.search import find_best_move
    from logic.ai.weights import load_weights

    weights = load_weights("tier1")
    state = create_initial_state(level=level, mode="ai", ai_difficulty="hard")
    state.ai_player = "white"

    # Setup フェーズ
    if state.phase == "setup":
        for _ in range(200):
            if state.phase != "setup":
                break
            cur = state.current_player
            state.ai_player = cur
            ok, _ = _handle_setup(state, cur)
            if not ok:
                break

    positions = []
    move_count = 0

    while not state.game_over and move_count < max_moves:
        current = state.current_player

        # 最善手 + pvs スコアを同時取得（追加コストなし）
        result = find_best_move(
            state, current,
            max_depth=12,
            time_limit=time_limit,
            noise=10,
            max_moves=15,
            weights=weights,
            return_score=True,
        )

        if result is None:
            state.game_over = True
            state.winner = "white" if current == "black" else "black"
            break

        best_move, pvs_score = result

        # 3 手に 1 回サンプリング
        if move_count % sample_rate == 0:
            # 白視点に正規化してクリップ
            score_white = pvs_score if current == "white" else -pvs_score
            score_white = max(-_SCORE_CLIP, min(_SCORE_CLIP, score_white))
            positions.append((serialize_state(state), score_white))

        # 手を適用
        ok = False
        if best_move[0] == "board":
            ok, _ = apply_move(state, best_move[1], best_move[2],
                               best_move[3], best_move[4], best_move[5])
        elif best_move[0] == "arata":
            ok, _ = apply_arata(state, best_move[1], best_move[2], best_move[3])
        elif best_move[0] == "boushou":
            ok, _ = apply_boushou(state, best_move[1], best_move[2],
                                  best_move[3], best_move[4], best_move[5])
        if not ok:
            break
        move_count += 1

    return positions


def generate(
    out_path: str = "data/tuning/distill_positions.pkl",
    level: str = "joukyuu",
    time_budget_hours: float = 8.0,
    parallel: int = 4,
    move_time_limit: float = 1.0,
    max_moves: int = 300,
    sample_rate: int = 3,
) -> int:
    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 見積もり: joukyuu で 1s/手 → 約 75 秒 / 局
    est_secs_per_game = 75
    est_games = max(int(time_budget_hours * 3600 * parallel / est_secs_per_game), 8)
    tasks = [(level, move_time_limit, max_moves, sample_rate)] * est_games

    print(f"[distill-gen] level={level}  tl={move_time_limit}s/手  "
          f"parallel={parallel}  budget={time_budget_hours}h  est_games={est_games}",
          flush=True)

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
                avg_score = (sum(s for _, s in all_positions) / len(all_positions)
                             if all_positions else 0)
                print(f"  games={game_count:4d}  positions={len(all_positions):6d}"
                      f"  avg_score={avg_score:+.0f}"
                      f"  elapsed={elapsed/3600:.2f}h  remaining={remaining/3600:.2f}h",
                      flush=True)

            if time.time() >= deadline:
                print("[distill-gen] 時間切れ、停止", flush=True)
                pool.terminate()
                break

    with open(out, "wb") as f:
        pickle.dump(all_positions, f)

    print(f"[distill-gen] 完了  games={game_count}  positions={len(all_positions)}"
          f"  saved={out}", flush=True)
    return len(all_positions)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours",    type=float, default=8.0)
    parser.add_argument("--parallel", type=int,   default=4)
    parser.add_argument("--level",    default="joukyuu")
    parser.add_argument("--tl",       type=float, default=1.0, dest="time_limit")
    parser.add_argument("--out",      default="data/tuning/distill_positions.pkl")
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
