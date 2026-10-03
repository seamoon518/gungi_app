"""A9/A10: AI 同士の通し対局シミュレーション（手動実行用。pytest の収集対象外）

例:
  python -m tests.sim_ai_vs_ai --out /tmp/sim.jsonl --workers 3 \
      --match nyumon:easy:easy:2 --match chukyuu:hard:easy:1 --max-plies 150
"""

import argparse
import json
import random
import statistics
import time
from collections import Counter
from multiprocessing import Pool


def play_one(args):
    level, bdiff, wdiff, max_plies, seed = args
    random.seed(seed)
    from logic.game_engine import create_initial_state
    from logic.ai import engine as ai_engine
    from logic.ai.search import find_best_move as orig_find

    infos = []

    def wrapped(*a, **kw):
        info = {}
        t = time.time()
        r = orig_find(*a, info=info, **kw)
        info["time"] = time.time() - t
        info["player"] = a[1]
        infos.append(info)
        return r

    ai_engine.find_best_move = wrapped
    s = create_initial_state(level, "ai_vs_ai", None, bdiff, wdiff)
    plies, errors, t0 = 0, [], time.time()
    pieces_start = None
    while not s.game_over and plies < max_plies:
        was_play = s.phase == "play"
        if was_play and pieces_start is None:
            pieces_start = sum(len(st) for row in s.board for st in row)
        ok, err = ai_engine.get_ai_move_and_apply(s)
        if not ok:
            errors.append(err)
            break
        if was_play:
            plies += 1
    pieces_end = sum(len(st) for row in s.board for st in row)
    if s.game_over:
        result = s.winner or "draw"
    else:
        result = "cap" if not errors else "error"
    by_player = {}
    for p in ("black", "white"):
        xs = [i for i in infos if i["player"] == p]
        if xs:
            by_player[p] = {
                "avg_time": round(statistics.mean(i["time"] for i in xs), 2),
                "max_time": round(max(i["time"] for i in xs), 2),
                "avg_depth": round(statistics.mean(i.get("depth", 0) for i in xs), 2),
                "depth0": sum(1 for i in xs if i.get("depth", 0) == 0),
                "n": len(xs),
            }
    return {
        "level": level, "black": bdiff, "white": wdiff, "seed": seed,
        "result": result, "plies": plies, "errors": errors,
        "max_repetition": max(Counter(s.position_history).values()) if s.position_history else 0,
        "captured": (pieces_start or 0) - pieces_end,
        "by_player": by_player, "wall": round(time.time() - t0, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", action="append", required=True,
                    help="level:black_diff:white_diff:games")
    ap.add_argument("--max-plies", type=int, default=150)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    jobs, seed = [], 1
    for m in a.match:
        level, b, w, n = m.split(":")
        for _ in range(int(n)):
            jobs.append((level, b, w, a.max_plies, seed))
            seed += 1
    with Pool(a.workers) as pool, open(a.out, "w", encoding="utf-8") as f:
        for r in pool.imap_unordered(play_one, jobs):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
