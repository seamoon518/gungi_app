"""
prod_smoke.py: デプロイ済みバックエンドに対して AI 同士の対局を API 経由で進め、
エラーが出ないこと・1 手あたりの応答時間を確認する（ブラウザを使わない簡易確認）。

    python -m scripts.prod_smoke --base https://gungiapp-production.up.railway.app --plies 30
"""

import argparse
import json
import sys
import time
import urllib.request

LEVELS = ["nyumon", "shokyuu", "chukyuu", "joukyuu"]
DIFFS = ["easy", "normal", "hard"]


def call(base: str, path: str, body=None, timeout: float = 120.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None or path.endswith("ai-move") else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def play(base: str, level: str, diff: str, plies: int) -> dict:
    s = call(base, "/game/new", {"level": level, "mode": "ai_vs_ai",
                                 "ai_difficulty_black": diff, "ai_difficulty_white": diff})
    gid = s["game_id"]
    times, n = [], 0
    while not s["game_over"] and n < plies:
        t = time.time()
        s = call(base, f"/game/{gid}/ai-move")
        dt = time.time() - t
        if s.get("phase") == "play":
            times.append(dt)
            n += 1
    return {"level": level, "diff": diff, "plies": n, "game_over": s["game_over"],
            "max_s": round(max(times), 2) if times else None,
            "avg_s": round(sum(times) / len(times), 2) if times else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://gungiapp-production.up.railway.app")
    ap.add_argument("--plies", type=int, default=30)
    ap.add_argument("--diffs", default=",".join(DIFFS))
    ap.add_argument("--levels", default=",".join(LEVELS))
    a = ap.parse_args()
    failed = 0
    for level in a.levels.split(","):
        for diff in a.diffs.split(","):
            try:
                r = play(a.base, level, diff, a.plies)
                print(json.dumps(r, ensure_ascii=False), flush=True)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(json.dumps({"level": level, "diff": diff, "error": repr(e)}, ensure_ascii=False), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
