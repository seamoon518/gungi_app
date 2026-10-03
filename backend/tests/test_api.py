"""A1(API) / A6: 待った / A7: 投了 / A12: 同時リクエスト / A13: 不正入力"""

import threading

import pytest
from fastapi.testclient import TestClient

from main import app
from logic.ai import engine as ai_engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def fast_ai(monkeypatch):
    """API テストでは AI の思考時間を短縮する（手の合法性は変わらない）。"""
    fast = {k: {**v, "time_limit": 0.2} for k, v in ai_engine._DIFFICULTY_PARAMS.items()}
    monkeypatch.setattr(ai_engine, "_DIFFICULTY_PARAMS", fast)


def new_game(**body):
    r = client.post("/game/new", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def move(gid, fr, fc, tr, tc, action="auto"):
    return client.post(f"/game/{gid}/move", json={
        "from_row": fr, "from_col": fc, "to_row": tr, "to_col": tc, "action": action})


def top(state, r, c):
    st = state["board"][r][c]["stack"]
    return (st[-1]["type"], st[-1]["owner"]) if st else None


# ── A1: 対局作成 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("level", ["nyumon", "shokyuu", "chukyuu", "joukyuu"])
@pytest.mark.parametrize("mode,extra,ai_player", [
    ("pvp", {}, None),
    ("ai", {"ai_difficulty": "easy", "human_player": "black"}, "white"),
    ("ai", {"ai_difficulty": "hard", "human_player": "white"}, "black"),
    ("ai_vs_ai", {"ai_difficulty_black": "easy", "ai_difficulty_white": "hard"}, "both"),
])
def test_new_game_all_modes(level, mode, extra, ai_player):
    s = new_game(level=level, mode=mode, **extra)
    assert s["level"] == level and s["mode"] == mode and s["ai_player"] == ai_player
    assert s["move_count"] == 0 and not s["game_over"]
    assert client.get(f"/game/{s['game_id']}/state").json()["board"] == s["board"]


def test_unknown_game_404():
    assert client.get("/game/nope/state").status_code == 404
    assert client.post("/game/nope/ai-move").status_code == 404


# ── A6: 待った ───────────────────────────────────────────────────────────────

def test_undo_pvp_one_ply():
    s = new_game(level="nyumon", mode="pvp")
    gid = s["game_id"]
    assert move(gid, 6, 0, 5, 0).status_code == 200
    assert move(gid, 2, 0, 3, 0).status_code == 200
    r = client.post(f"/game/{gid}/undo")
    assert r.status_code == 200
    u = r.json()
    assert u["current_player"] == "white" and u["move_count"] == 1
    assert top(u, 2, 0) == ("兵", "white") and top(u, 5, 0) == ("兵", "black")


def test_undo_nothing_to_undo():
    s = new_game(level="nyumon", mode="pvp")
    assert client.post(f"/game/{s['game_id']}/undo").status_code == 400


def test_undo_ai_mode_reverts_ai_reply_too():
    s = new_game(level="nyumon", mode="ai", ai_difficulty="easy", human_player="black")
    gid = s["game_id"]
    assert move(gid, 6, 0, 5, 0).status_code == 200
    r = client.post(f"/game/{gid}/ai-move")
    assert r.status_code == 200 and r.json()["current_player"] == "black"
    u = client.post(f"/game/{gid}/undo").json()
    assert u["current_player"] == "black" and u["move_count"] == 0
    assert u["board"] == s["board"]


def test_undo_after_rejected_move_still_reverts_last_real_move():
    """H6: 失敗した操作が「待った」の記録を汚さないこと。"""
    s = new_game(level="nyumon", mode="pvp")
    gid = s["game_id"]
    assert move(gid, 6, 0, 5, 0).status_code == 200
    # 白番に黒駒を動かそうとする（失敗）×2
    assert move(gid, 6, 2, 5, 2).status_code == 400
    assert move(gid, 6, 2, 5, 2).status_code == 400
    u = client.post(f"/game/{gid}/undo").json()
    assert u["move_count"] == 0 and u["current_player"] == "black"
    assert u["board"] == s["board"]


def test_undo_blocked_after_game_over():
    s = new_game(level="nyumon", mode="pvp")
    gid = s["game_id"]
    client.post(f"/game/{gid}/resign")
    assert client.post(f"/game/{gid}/undo").status_code == 400


# ── A7: 投了 ─────────────────────────────────────────────────────────────────

def test_resign_current_player_loses():
    s = new_game(level="nyumon", mode="pvp")
    gid = s["game_id"]
    move(gid, 6, 0, 5, 0)
    r = client.post(f"/game/{gid}/resign").json()
    assert r["game_over"] and r["winner"] == "black"   # 白番で投了 → 黒の勝ち
    assert client.post(f"/game/{gid}/resign").status_code == 400


# ── A12: 同時リクエスト ───────────────────────────────────────────────────────

def _concurrent(fn, n=2):
    results, barrier = [None] * n, threading.Barrier(n)

    def run(i):
        barrier.wait()
        results[i] = fn()
    ths = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    return results


def test_concurrent_ai_move_requests_keep_state_consistent():
    s = new_game(level="nyumon", mode="ai_vs_ai",
                 ai_difficulty_black="easy", ai_difficulty_white="easy")
    gid = s["game_id"]
    rs = _concurrent(lambda: client.post(f"/game/{gid}/ai-move"))
    ok = [r for r in rs if r.status_code == 200]
    final = client.get(f"/game/{gid}/state").json()
    # 成功したリクエストの数だけ手が進み、エラーで止まらないこと
    assert all(r.status_code in (200, 409) for r in rs), [r.text for r in rs]
    assert final["move_count"] == len(ok) >= 1
    assert final["current_player"] == ("white" if len(ok) % 2 else "black")


def test_concurrent_duplicate_move_applied_once():
    s = new_game(level="nyumon", mode="pvp")
    gid = s["game_id"]
    rs = _concurrent(lambda: move(gid, 6, 0, 5, 0), n=4)
    assert sum(r.status_code == 200 for r in rs) == 1
    final = client.get(f"/game/{gid}/state").json()
    assert final["move_count"] == 1 and final["current_player"] == "white"


# ── A13: 不正入力 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("coords", [
    (9, 0, 5, 0), (6, 0, 9, 0), (6, 9, 5, 0), (100, 100, 0, 0),
])
def test_out_of_range_coords_rejected_cleanly(coords):
    s = new_game(level="nyumon", mode="pvp")
    r = move(s["game_id"], *coords)
    assert 400 <= r.status_code < 500, (r.status_code, r.text)


def test_negative_index_cannot_teleport_piece():
    """from_row=-1 が Python の負インデックスで 9 段目として扱われないこと。"""
    s = new_game(level="nyumon", mode="pvp")
    gid = s["game_id"]
    r = move(gid, -1, 3, 0, 3)          # 黒の大(8,3) を白陣(0,3) へワープさせる試み
    assert 400 <= r.status_code < 500
    st = client.get(f"/game/{gid}/state").json()
    assert top(st, 0, 3) == ("中", "white") and st["move_count"] == 0


@pytest.mark.parametrize("path,body", [
    ("arata", {"piece_type": "小", "to_row": -1, "to_col": 0}),
    ("arata", {"piece_type": "小", "to_row": 9, "to_col": 0}),
    ("boushou", {"from_row": -1, "from_col": 0, "to_row": 0, "to_col": 0, "target_index": 0}),
])
def test_other_endpoints_reject_bad_coords(path, body):
    s = new_game(level="nyumon", mode="pvp")
    r = client.post(f"/game/{s['game_id']}/{path}", json=body)
    assert 400 <= r.status_code < 500, (r.status_code, r.text)


def test_ai_move_rejected_in_pvp_and_human_turn():
    s = new_game(level="nyumon", mode="pvp")
    assert client.post(f"/game/{s['game_id']}/ai-move").status_code == 400
    s = new_game(level="nyumon", mode="ai", ai_difficulty="easy", human_player="black")
    assert client.post(f"/game/{s['game_id']}/ai-move").status_code == 400
