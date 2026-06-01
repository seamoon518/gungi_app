"""
benchmark.py: 2つの AI バージョンを N 局自己対戦させて勝率を出力する。

使用例:
    python -m scripts.benchmark \\
        --baseline tier0 --candidate tier0 \\
        --games 10 --level joukyuu \\
        --parallel 4 --time-budget 5 \\
        --output data/benchmarks/
"""

import argparse
import json
import math
import os
import pathlib
import time
import uuid
from multiprocessing import Pool
from typing import Optional


def _run_one(args: tuple) -> dict:
    """multiprocessing ワーカー: 1局を実行して結果 dict を返す。"""
    baseline, candidate, level, max_moves, time_budget, black_is_a, game_idx, run_id, save_dir, baseline_tl, candidate_tl = args

    # ワーカーは独立プロセスなので sys.path 調整が必要な場合がある
    import sys
    import pathlib
    backend_dir = str(pathlib.Path(__file__).parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from scripts.selfplay import play_game

    baseline_cfg = {"weights": baseline, "max_depth": 6, "time_limit": baseline_tl, "noise": 0, "max_moves": 15}
    candidate_cfg = {"weights": candidate, "max_depth": 6, "time_limit": candidate_tl, "noise": 0, "max_moves": 15}

    record = play_game(
        ai_a_config=baseline_cfg,
        ai_b_config=candidate_cfg,
        level=level,
        max_moves=max_moves,
        black_is_a=black_is_a,
    )
    record["game_index"] = game_idx
    record["black_is_a"] = black_is_a

    # 棋譜を個別ファイルに保存
    if save_dir:
        game_path = pathlib.Path(save_dir) / run_id / f"{game_idx:04d}.json"
        game_path.parent.mkdir(parents=True, exist_ok=True)
        with open(game_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    return record


def _elo_diff(wins: int, losses: int) -> Optional[float]:
    """勝ち/負け数から Elo 差分を推定（引き分けは無視）。どちらかが 0 なら None。"""
    if wins == 0 or losses == 0:
        return None
    return round(400 * math.log10(wins / losses), 1)


def run_benchmark(
    baseline: str,
    candidate: str,
    games: int = 100,
    level: str = "joukyuu",
    parallel: int = 4,
    time_budget: float = 5.0,
    baseline_time_budget: Optional[float] = None,
    candidate_time_budget: Optional[float] = None,
    max_moves: int = 300,
    output_dir: Optional[str] = None,
    save_games: bool = True,
) -> dict:
    """
    ベンチマークを実行してサマリ dict を返す。

    Parameters
    ----------
    baseline, candidate : str
        weights 名 (例: "tier0", "tier1")
    games : int
        総対局数（先後各 games//2 局）
    level : str
        ゲームレベル
    parallel : int
        並列プロセス数
    time_budget : float
        1手あたりの思考時間上限（秒）
    max_moves : int
        1局の手数上限
    output_dir : str | None
        ベンチマーク JSON の保存先ディレクトリ
    save_games : bool
        棋譜 JSON を games/ に保存するか
    """
    run_id = str(uuid.uuid4())[:8]
    save_dir = output_dir if save_games else None
    btl = baseline_time_budget if baseline_time_budget is not None else time_budget
    ctl = candidate_time_budget if candidate_time_budget is not None else time_budget

    # 先後入れ替え: 前半は ai_a=黒, 後半は ai_a=白
    half = games // 2
    tasks = []
    for i in range(half):
        tasks.append((baseline, candidate, level, max_moves, time_budget, True, i, run_id, save_dir, btl, ctl))
    for i in range(games - half):
        tasks.append((baseline, candidate, level, max_moves, time_budget, False, half + i, run_id, save_dir, btl, ctl))

    tl_info = f"baseline={btl}s candidate={ctl}s" if btl != ctl else f"tl={btl}s"
    print(f"[benchmark] {baseline} vs {candidate} | {games} games | level={level} | parallel={parallel} | {tl_info}")
    t_start = time.time()

    results = []
    if parallel > 1:
        with Pool(processes=parallel) as pool:
            for i, rec in enumerate(pool.imap_unordered(_run_one, tasks), 1):
                results.append(rec)
                print(f"  [{i:>3}/{games}] result={rec['result']:12s} moves={rec['total_moves']:>3} "
                      f"avg_ms={rec['avg_thinking_time_ms']:>5}", flush=True)
    else:
        for i, task in enumerate(tasks, 1):
            rec = _run_one(task)
            results.append(rec)
            print(f"  [{i:>3}/{games}] result={rec['result']:12s} moves={rec['total_moves']:>3} "
                  f"avg_ms={rec['avg_thinking_time_ms']:>5}", flush=True)

    elapsed = time.time() - t_start

    wins   = sum(1 for r in results if r["result"] == "ai_a_win")
    losses = sum(1 for r in results if r["result"] == "ai_b_win")
    draws  = sum(1 for r in results if r["result"] == "draw")

    by_term = {}
    for r in results:
        t = r["termination"]
        by_term[t] = by_term.get(t, 0) + 1

    avg_moves = round(sum(r["total_moves"] for r in results) / len(results), 1) if results else 0
    avg_ms    = round(sum(r["avg_thinking_time_ms"] for r in results) / len(results), 1) if results else 0
    win_rate  = round(wins / games, 4) if games > 0 else 0.0

    summary = {
        "run_id": run_id,
        "baseline": baseline,
        "candidate": candidate,
        "level": level,
        "games": games,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": win_rate,
        "elo_diff": _elo_diff(wins, losses),
        "terminations": by_term,
        "avg_moves": avg_moves,
        "avg_thinking_time_ms": avg_ms,
        "elapsed_sec": round(elapsed, 1),
    }

    print(f"\n[result] wins={wins} draws={draws} losses={losses} "
          f"win_rate={win_rate:.1%} elo_diff={summary['elo_diff']}")
    print(f"[result] terminations={by_term}")
    print(f"[result] avg_moves={avg_moves} avg_ms={avg_ms} elapsed={elapsed:.1f}s")

    if output_dir:
        out_path = pathlib.Path(output_dir) / f"{run_id}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"[saved] {out_path}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="軍儀 AI ベンチマーク")
    parser.add_argument("--baseline",    default="tier0")
    parser.add_argument("--candidate",   default="tier1")
    parser.add_argument("--games",       type=int,   default=100)
    parser.add_argument("--level",       default="joukyuu",
                        choices=["nyumon", "shokyuu", "chukyuu", "joukyuu"])
    parser.add_argument("--parallel",    type=int,   default=4)
    parser.add_argument("--time-budget",    type=float, default=5.0,  dest="time_budget")
    parser.add_argument("--baseline-tl",   type=float, default=None, dest="baseline_tl",
                        help="baseline の思考時間（省略時は --time-budget を使用）")
    parser.add_argument("--candidate-tl",  type=float, default=None, dest="candidate_tl",
                        help="candidate の思考時間（省略時は --time-budget を使用）")
    parser.add_argument("--max-moves",     type=int,   default=300, dest="max_moves")
    parser.add_argument("--output",      default="data/benchmarks/", dest="output_dir")
    parser.add_argument("--no-save-games", action="store_true", dest="no_save_games")
    args = parser.parse_args()

    run_benchmark(
        baseline=args.baseline,
        candidate=args.candidate,
        games=args.games,
        level=args.level,
        parallel=args.parallel,
        time_budget=args.time_budget,
        baseline_time_budget=args.baseline_tl,
        candidate_time_budget=args.candidate_tl,
        max_moves=args.max_moves,
        output_dir=args.output_dir,
        save_games=not args.no_save_games,
    )


if __name__ == "__main__":
    main()
