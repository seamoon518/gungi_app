import uuid
from typing import Dict

from fastapi import APIRouter, HTTPException

from models.game_state import GameState
from logic.game_engine import (
    create_initial_state, apply_move, apply_arata,
    apply_setup_place, apply_setup_done,
)
from logic.ai.engine import get_ai_move_and_apply
from logic.movement import get_valid_moves
from logic.arata import get_valid_arata_positions
from logic.setup import get_valid_setup_positions
from api.schemas import (
    NewGameRequest, MoveRequest, ValidMovesResponse,
    ArataRequest, ValidArataResponse, SetupPlaceRequest,
)

router = APIRouter(prefix="/game", tags=["game"])

_games: Dict[str, GameState] = {}


@router.post("/new")
def new_game(req: NewGameRequest):
    game_id = str(uuid.uuid4())
    _games[game_id] = create_initial_state(req.level, req.mode, req.ai_difficulty)
    return _games[game_id].to_dict(game_id)


@router.get("/{game_id}/state")
def get_state(game_id: str):
    return _get_or_404(game_id).to_dict(game_id)


@router.get("/{game_id}/valid-moves")
def valid_moves(game_id: str, row: int, col: int) -> ValidMovesResponse:
    state = _get_or_404(game_id)
    if state.phase == "setup":
        return ValidMovesResponse(valid_moves=[], enemy_tsuke_moves=[])
    if not (0 <= row < 9 and 0 <= col < 9):
        raise HTTPException(status_code=400, detail="Row/col out of bounds.")
    options = get_valid_moves(
        state.board, row, col,
        state.rules.max_stack, state.rules.sui_can_tsuke,
    )
    return ValidMovesResponse(
        valid_moves=[[r, c] for r, c in options.valid_moves],
        enemy_tsuke_moves=[[r, c] for r, c in options.enemy_tsuke_moves],
    )


@router.get("/{game_id}/valid-arata")
def valid_arata(game_id: str) -> ValidArataResponse:
    state = _get_or_404(game_id)
    if state.phase == "setup":
        return ValidArataResponse(valid_positions=[])
    positions = get_valid_arata_positions(
        state.board, state.current_player, state.rules.max_stack
    )
    return ValidArataResponse(valid_positions=[[r, c] for r, c in positions])


@router.post("/{game_id}/move")
def make_move(game_id: str, req: MoveRequest):
    state = _get_or_404(game_id)
    success, error = apply_move(
        state, req.from_row, req.from_col, req.to_row, req.to_col, req.action
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return state.to_dict(game_id)


@router.post("/{game_id}/arata")
def place_arata(game_id: str, req: ArataRequest):
    state = _get_or_404(game_id)
    success, error = apply_arata(state, req.piece_type, req.to_row, req.to_col)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return state.to_dict(game_id)


@router.post("/{game_id}/resign")
def resign(game_id: str):
    state = _get_or_404(game_id)
    if state.game_over:
        raise HTTPException(status_code=400, detail="Game is already over.")
    loser = state.current_player
    state.game_over = True
    state.winner = "white" if loser == "black" else "black"
    return state.to_dict(game_id)


# ── Setup phase endpoints (中級/上級) ───────────────────────────────────────────

@router.get("/{game_id}/setup/valid-positions")
def setup_valid_positions(game_id: str) -> ValidArataResponse:
    state = _get_or_404(game_id)
    if state.phase != "setup":
        return ValidArataResponse(valid_positions=[])
    positions = get_valid_setup_positions(
        state.board, state.current_player, state.rules.max_stack
    )
    return ValidArataResponse(valid_positions=[[r, c] for r, c in positions])


@router.post("/{game_id}/setup/place")
def setup_place(game_id: str, req: SetupPlaceRequest):
    state = _get_or_404(game_id)
    success, error = apply_setup_place(state, req.piece_type, req.to_row, req.to_col)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return state.to_dict(game_id)


@router.post("/{game_id}/setup/done")
def setup_done(game_id: str):
    state = _get_or_404(game_id)
    success, error = apply_setup_done(state)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return state.to_dict(game_id)


@router.post("/{game_id}/ai-move")
def ai_move(game_id: str):
    """AI の手番を処理する（setup / play 両フェーズ対応）"""
    state = _get_or_404(game_id)
    if state.mode != "ai":
        raise HTTPException(status_code=400, detail="AI対戦モードではありません。")
    if state.game_over:
        raise HTTPException(status_code=400, detail="ゲームは終了しています。")
    if state.current_player != state.ai_player:
        raise HTTPException(status_code=400, detail="AI の手番ではありません。")
    success, error = get_ai_move_and_apply(state)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return state.to_dict(game_id)


def _get_or_404(game_id: str) -> GameState:
    state = _games.get(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found.")
    return state
