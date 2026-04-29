"""全レベル × 全難易度の AI 動作確認スクリプト"""
import time
from logic.game_engine import create_initial_state, apply_setup_place, apply_setup_done, apply_move
from logic.ai.engine import get_ai_move_and_apply
from logic.ai.search import get_all_game_moves
from logic.setup import has_placed_sui
from models.piece import PieceType


def run_test(level, diff):
    state = create_initial_state(level, "ai", diff)

    # setup フェーズ（中級・上級のみ）
    if state.phase == "setup":
        for _ in range(60):
            if state.phase != "setup":
                break
            if state.current_player == "black":
                if not has_placed_sui(state.board, "black"):
                    ok, err = apply_setup_place(state, PieceType.SUI.value, 8, 4)
                    if not ok:
                        return False, "黒帅配置失敗: " + err
                else:
                    apply_setup_done(state)
            else:
                ok, err = get_ai_move_and_apply(state)
                if not ok:
                    return False, "AI setup失敗: " + err

    if state.phase != "play":
        return False, "setup未完了"

    # ゲームフェーズ: 黒が合法手を1手選んで指す
    moves = get_all_game_moves(state, "black")
    board_move = next((m for m in moves if m[0] == "board"), None)
    if board_move:
        apply_move(state, board_move[1], board_move[2], board_move[3], board_move[4], board_move[5])
    elif moves:
        # arata のみ
        m = moves[0]
        from logic.game_engine import apply_arata
        apply_arata(state, m[1], m[2], m[3])
    else:
        return False, "黒の合法手なし"

    # AI が返す
    t0 = time.time()
    ok, err = get_ai_move_and_apply(state)
    elapsed = time.time() - t0
    if not ok:
        return False, f"AI game失敗: {err}"
    return True, f"{elapsed:.2f}s"


levels = ["nyumon", "shokyuu", "chukyuu", "joukyuu"]
diffs = ["easy", "normal", "hard"]

print(f"{'level+diff':<20} {'result':<6} {'time'}")
print("-" * 40)
for level in levels:
    for diff in diffs:
        ok, info = run_test(level, diff)
        status = "OK" if ok else "NG"
        print(f"{level}+{diff:<10} {status:<6} {info}")
