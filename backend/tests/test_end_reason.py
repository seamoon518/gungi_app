"""終局理由・AI同士の手数上限・投了の扱い・対局数の上限"""

import pytest
from fastapi.testclient import TestClient

from main import app
from api import router as router_mod
from logic import game_engine
from logic.game_engine import create_initial_state, apply_move
from tests.helpers import make_state

client = TestClient(app)

CYCLE = [(6, 0, 5, 0), (2, 0, 3, 0), (5, 0, 6, 0), (3, 0, 2, 0)]
# 千日手にならない往復（駒を毎回変えて同一局面の 4 回目を避ける）
WALK = [(6, 0, 5, 0), (2, 0, 3, 0), (6, 8, 5, 8), (2, 8, 3, 8)]


def test_end_reason_sui_and_sennichite():
    s = make_state({(5, 4): [("兵", "black")], (4, 4): [("帥", "white")], (8, 0): [("帥", "black")]})
    apply_move(s, 5, 4, 4, 4)
    assert s.end_reason == "sui" and s.to_dict("x")["end_reason"] == "sui"

    s = create_initial_state("nyumon")
    i = 0
    while not s.game_over:
        assert apply_move(s, *CYCLE[i % 4])[0]
        i += 1
    assert s.end_reason == "sennichite" and s.winner is None


def test_ai_vs_ai_move_limit_draw(monkeypatch):
    monkeypatch.setattr(game_engine, "MAX_PLIES_AI_VS_AI", 4)
    s = create_initial_state("nyumon", "ai_vs_ai", None, "easy", "easy")
    for mv in WALK:
        assert not s.game_over
        assert apply_move(s, *mv)[0]
    assert s.game_over and s.winner is None and s.end_reason == "move_limit"
    assert len(s.move_history) == 4


@pytest.mark.parametrize("mode", ["pvp", "ai"])
def test_move_limit_only_for_ai_vs_ai(mode, monkeypatch):
    monkeypatch.setattr(game_engine, "MAX_PLIES_AI_VS_AI", 4)
    s = create_initial_state("nyumon", mode, "easy")
    for mv in WALK:
        assert apply_move(s, *mv)[0]
    assert not s.game_over


def test_resign_reason_and_ai_mode_human_always_loses():
    r = client.post("/game/new", json={"level": "nyumon", "mode": "ai", "ai_difficulty": "easy",
                                       "human_player": "white"}).json()
    # 黒(AI)の手番のうちに投了リクエストが届いても、負けるのは人間(白)
    res = client.post(f"/game/{r['game_id']}/resign").json()
    assert res["winner"] == "black" and res["end_reason"] == "resign"


def test_old_games_are_evicted(monkeypatch):
    monkeypatch.setattr(router_mod, "MAX_GAMES", 3)
    ids = [client.post("/game/new", json={"level": "nyumon"}).json()["game_id"] for _ in range(3)]
    client.get(f"/game/{ids[0]}/state")            # ids[0] を最近使ったことにする
    newest = client.post("/game/new", json={"level": "nyumon"}).json()["game_id"]
    assert client.get(f"/game/{ids[1]}/state").status_code == 404   # 最も使われていない対局が消える
    for gid in (ids[0], ids[2], newest):
        assert client.get(f"/game/{gid}/state").status_code == 200
