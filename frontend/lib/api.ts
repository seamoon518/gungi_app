import {
  GameState, ValidMovesResponse, ValidArataResponse,
  MoveAction, GameLevel, GameMode, AiDifficulty,
} from "@/types/game";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8002";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  newGame: (
    level: GameLevel = "nyumon",
    mode: GameMode = "pvp",
    aiDifficulty?: AiDifficulty,
  ): Promise<GameState> =>
    request("/game/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level, mode, ai_difficulty: aiDifficulty ?? null }),
    }),

  getState: (gameId: string): Promise<GameState> =>
    request(`/game/${gameId}/state`),

  getValidMoves: (gameId: string, row: number, col: number): Promise<ValidMovesResponse> =>
    request(`/game/${gameId}/valid-moves?row=${row}&col=${col}`),

  getValidArata: (gameId: string): Promise<ValidArataResponse> =>
    request(`/game/${gameId}/valid-arata`),

  move: (
    gameId: string,
    fromRow: number, fromCol: number,
    toRow: number, toCol: number,
    action: MoveAction = "auto"
  ): Promise<GameState> =>
    request(`/game/${gameId}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from_row: fromRow, from_col: fromCol, to_row: toRow, to_col: toCol, action }),
    }),

  arata: (gameId: string, pieceType: string, toRow: number, toCol: number): Promise<GameState> =>
    request(`/game/${gameId}/arata`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ piece_type: pieceType, to_row: toRow, to_col: toCol }),
    }),

  resign: (gameId: string): Promise<GameState> =>
    request(`/game/${gameId}/resign`, { method: "POST" }),

  // ── Setup phase (中級/上級) ─────────────────────────────────────────────────

  getValidSetupPositions: (gameId: string): Promise<ValidArataResponse> =>
    request(`/game/${gameId}/setup/valid-positions`),

  setupPlace: (gameId: string, pieceType: string, toRow: number, toCol: number): Promise<GameState> =>
    request(`/game/${gameId}/setup/place`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ piece_type: pieceType, to_row: toRow, to_col: toCol }),
    }),

  setupDone: (gameId: string): Promise<GameState> =>
    request(`/game/${gameId}/setup/done`, { method: "POST" }),

  aiMove: (gameId: string): Promise<GameState> =>
    request(`/game/${gameId}/ai-move`, { method: "POST" }),
};
