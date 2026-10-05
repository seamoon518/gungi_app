"""
arena.py: 2つの AI（別バージョンのコードでも可）を多数対局させ、勝率とレーティング差を出す。

各 AI は「エンジンサーバー」という別プロセスで動かす。エンジンサーバーは指定したソースツリー
（例: 修正前のコードを git worktree で取り出したディレクトリ）の logic をそのまま使うため、
新旧のコードを同じ条件で戦わせられる。対局の進行（終局・千日手・手数上限）は現在のコードが判定する。

使用例（現行コードの「難しい」と、worktree に取り出した旧版の「難しい」を 200 局）:
    python -m scripts.arena \\
        --a tree=.,diff=hard,time=0.5 --b tree=/tmp/old/backend,diff=hard,time=0.5 \\
        --levels nyumon,shokyuu,chukyuu,joukyuu --games 200 --workers 3 --out /tmp/arena.jsonl

プレイヤー指定（カンマ区切り key=value）:
    tree  : backend ディレクトリ（既定: このスクリプトのある backend）
    diff  : 難易度 easy / normal / hard（既定 hard）
    time  : 1手の思考時間（秒）。指定すると難易度の time_limit を上書き
    depth : 最大深さの上書き
    noise : ノイズの上書き
    weights: 重みファイル名の上書き（例 tier1）
    moves : 各局面で読む候補手数（max_moves）の上書き
"""

import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from multiprocessing import Pool
from typing import Dict, Optional

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 局面のシリアライズ（どのバージョンのコードでも読める最小限の形式） ────────

def dump_state(state) -> dict:
    return {
        "board": [[[[p.type.value, p.owner] for p in st] for st in row] for row in state.board],
        "current_player": state.current_player,
        "hand": {k: [p.type.value for p in v] for k, v in state.hand_pieces.items()},
        "level": state.level,
        "phase": state.phase,
        "setup_done": dict(state.setup_done),
        "position_history": list(state.position_history),
        "move_count": len(state.move_history),
    }


def load_state(d: dict):
    """d から GameState を組み立てる（エンジンサーバー側で、そのツリーの模型を使って呼ばれる）。"""
    from models.game_state import GameState, Move, RULES_BY_LEVEL
    from models.piece import Piece, PieceType
    board = [[[Piece(PieceType(t), o) for t, o in st] for st in row] for row in d["board"]]
    hand = {k: [Piece(PieceType(t), k) for t in v] for k, v in d["hand"].items()}
    s = GameState(
        board=board, current_player=d["current_player"], hand_pieces=hand,
        level=d["level"], mode="ai_vs_ai", phase=d["phase"],
        setup_done=dict(d["setup_done"]), rules=RULES_BY_LEVEL[d["level"]],
    )
    s.ai_player = "both"
    s.position_history = list(d["position_history"])
    # move_history は手数上限の判定にだけ使われる（中身は参照しない）
    s.move_history = [Move(-1, -1, -1, -1)] * d["move_count"]
    return s


# ── エンジンサーバー（--serve モード） ───────────────────────────────────────

def serve(tree: str) -> None:
    """標準入力から {"state", "params"} を受け取り、AI が指した後の局面を返す。"""
    sys.path.insert(0, os.path.abspath(tree))
    from logic.ai import engine as eng
    try:  # 高速エンジンがあるツリーでは、対局前にコンパイルを済ませる
        from logic.ai import fast
        fast.warmup()
    except ImportError:
        pass
    base = {k: dict(v) for k, v in eng._DIFFICULTY_PARAMS.items()}
    out = sys.stdout
    sys.stdout = sys.stderr      # エンジン側の print が通信を壊さないようにする
    for line in sys.stdin:
        req = json.loads(line)
        p = req["params"]
        diff = p.get("diff", "hard")
        params = dict(base[diff])
        for key, name in (("time", "time_limit"), ("depth", "max_depth"),
                          ("noise", "noise"), ("weights", "weights"), ("moves", "max_moves")):
            if key in p:
                params[name] = p[key]
        eng._DIFFICULTY_PARAMS[diff] = params
        random.seed(req.get("seed"))
        s = load_state(req["state"])
        s.ai_difficulty_black = s.ai_difficulty_white = diff
        ok, err = eng.get_ai_move_and_apply(s)
        res = {"ok": ok, "err": err, "state": dump_state(s),
               "game_over": s.game_over, "winner": s.winner}
        out.write(json.dumps(res) + "\n")
        out.flush()


class Engine:
    def __init__(self, spec: Dict[str, str]):
        self.spec = spec
        tree = spec.get("tree", BACKEND_DIR)
        self.proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--serve", tree],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=tree,
        )
        self.params = {k: (float(v) if k in ("time",) else int(v) if k in ("depth", "noise", "moves") else v)
                       for k, v in spec.items() if k != "tree"}

    def play(self, state_dict: dict, seed: int) -> dict:
        self.proc.stdin.write(json.dumps({"state": state_dict, "params": self.params, "seed": seed}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("engine process died")
        return json.loads(line)

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


_ENGINES: dict = {}


def _engine(spec: Dict[str, str]) -> "Engine":
    """エンジンプロセスはワーカーごとに使い回す（起動時のコンパイルを毎局しないため）。"""
    key = json.dumps(spec, sort_keys=True)
    if key not in _ENGINES:
        _ENGINES[key] = Engine(spec)
    return _ENGINES[key]


# ── 対局 ───────────────────────────────────────────────────────────────────

def _random_opening(state, plies: int, rng: random.Random) -> None:
    """序盤の数手をランダムに指して対局ごとに局面をばらつかせる（同じ seed なら同じ序盤）。"""
    from logic.ai.search import get_all_game_moves
    from logic.game_engine import apply_move, apply_arata
    for _ in range(plies):
        moves = [m for m in get_all_game_moves(state, state.current_player) if m[0] in ("board", "arata")]
        # 序盤の乱数手で駒を取り合わないよう、取る手・ツケる手は避ける
        quiet = [m for m in moves if m[0] == "arata" or m[5] == "auto"]
        m = rng.choice(quiet or moves)
        ok, err = (apply_move(state, *m[1:]) if m[0] == "board" else apply_arata(state, *m[1:]))
        assert ok, err
        if state.game_over:
            return


def play_game(args) -> dict:
    a_spec, b_spec, level, a_is_black, seed, max_plies, opening_plies = args
    sys.path.insert(0, BACKEND_DIR)
    from logic.game_engine import create_initial_state, _finish_turn  # noqa: F401

    engines = {"a": _engine(a_spec), "b": _engine(b_spec)}
    color_of = {"black": "a" if a_is_black else "b", "white": "b" if a_is_black else "a"}
    rng = random.Random(seed)
    t0 = time.time()
    try:
        state = create_initial_state(level, "ai_vs_ai", None, "hard", "hard")
        sd = dump_state(state)
        plies, over, winner, reason, err = 0, False, None, None, None
        while True:
            if sd["phase"] == "play" and plies == 0 and opening_plies:
                st = load_state(sd)  # 序盤の乱数手は現行ツリーで指す
                _random_opening(st, opening_plies, rng)
                sd = dump_state(st)
                plies = opening_plies
                if st.game_over:
                    over, winner, reason = True, st.winner, "opening"
                    break
            if plies >= max_plies:
                reason = "cap"
                break
            who = color_of[sd["current_player"]]
            was_play = sd["phase"] == "play"
            res = engines[who].play(sd, rng.randrange(1 << 30))
            if not res["ok"]:
                err = f"{who}: {res['err']}"
                over, winner, reason = True, ("white" if sd["current_player"] == "black" else "black"), "illegal"
                break
            sd = res["state"]
            if was_play:
                plies += 1
            if res["game_over"]:
                over, winner = True, res["winner"]
                reason = "sui" if winner else "draw"
                break
            # 千日手（同一局面 4 回）
            ph = sd["position_history"]
            if was_play and ph and ph.count(ph[-1]) >= 4:
                over, winner, reason = True, None, "sennichite"
                break
    finally:
        pass
    if winner is None:
        result = "draw"
    else:
        result = color_of[winner]
    return {"level": level, "a_is_black": a_is_black, "seed": seed, "result": result,
            "reason": reason, "plies": plies, "err": err, "sec": round(time.time() - t0, 1)}


# ── 集計 ───────────────────────────────────────────────────────────────────

def elo_summary(results) -> dict:
    n = len(results)
    w = sum(r["result"] == "a" for r in results)
    l = sum(r["result"] == "b" for r in results)
    d = n - w - l
    if n == 0:
        return {}
    score = (w + 0.5 * d) / n
    # 各局のスコアの標準偏差から 95% 信頼区間を出す
    var = (w * (1 - score) ** 2 + l * score ** 2 + d * (0.5 - score) ** 2) / n
    se = math.sqrt(var / n) if n > 1 else 0.5

    def to_elo(s):
        s = min(max(s, 1e-3), 1 - 1e-3)
        return -400 * math.log10(1 / s - 1)
    return {"games": n, "a_win": w, "b_win": l, "draw": d, "score": round(score, 3),
            "elo": round(to_elo(score)), "elo_lo": round(to_elo(score - 1.96 * se)),
            "elo_hi": round(to_elo(score + 1.96 * se))}


def parse_spec(s: str) -> Dict[str, str]:
    spec = dict(kv.split("=", 1) for kv in s.split(",") if kv)
    if "tree" in spec:
        spec["tree"] = os.path.abspath(spec["tree"])
    return spec


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2])
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="候補（例 tree=.,diff=hard,time=0.5）")
    ap.add_argument("--b", required=True, help="比較相手")
    ap.add_argument("--levels", default="nyumon,shokyuu,chukyuu,joukyuu")
    ap.add_argument("--games", type=int, default=100, help="合計局数（先後入れ替えのペアで数える）")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-plies", type=int, default=200)
    ap.add_argument("--opening-plies", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    a_spec, b_spec = parse_spec(a.a), parse_spec(a.b)
    levels = a.levels.split(",")
    jobs = []
    for i in range(a.games // 2):
        level = levels[i % len(levels)]
        seed = a.seed * 100_000 + i
        # 同じ序盤（同じ seed）で先後を入れ替えた 2 局を 1 組にする
        jobs.append((a_spec, b_spec, level, True, seed, a.max_plies, a.opening_plies))
        jobs.append((a_spec, b_spec, level, False, seed, a.max_plies, a.opening_plies))
    results = []
    with Pool(a.workers) as pool, open(a.out, "w", encoding="utf-8") as f:
        for r in pool.imap_unordered(play_game, jobs):
            results.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if len(results) % 10 == 0 or len(results) == len(jobs):
                print(json.dumps({"done": len(results), **elo_summary(results)}), flush=True)
    summary = {"all": elo_summary(results)}
    for lv in levels:
        summary[lv] = elo_summary([r for r in results if r["level"] == lv])
    errs = [r["err"] for r in results if r["err"]]
    summary["errors"] = errs[:5]
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
