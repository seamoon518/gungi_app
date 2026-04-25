import { GameState, ValidMovesResponse, ValidArataResponse, MoveAction } from "@/types/game";

const BASE = "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  newGame: (): Promise<GameState> =>
    request("/game/new", { method: "POST" }),

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
};
