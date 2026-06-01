export type Player = "black" | "white";

export type PieceType =
  | "帥" | "大" | "中" | "小" | "侍"
  | "槍" | "馬" | "忍" | "砦" | "兵"
  | "砲" | "筒" | "弓" | "謀";

export type GameLevel = "nyumon" | "shokyuu" | "chukyuu" | "joukyuu";
export type GameMode = "pvp" | "ai" | "ai_vs_ai";
export type AiDifficulty = "easy" | "normal" | "hard";

export interface Piece {
  type: PieceType;
  owner: Player;
}

export interface Cell {
  stack: Piece[];
}

export interface GameState {
  game_id: string;
  board: Cell[][];
  current_player: Player;
  hand_pieces: Record<Player, Piece[]>;
  game_over: boolean;
  winner: Player | null;
  move_count: number;
  level: GameLevel;
  phase: "setup" | "play";
  setup_done: Record<Player, boolean>;
  ai_player: Player | "both" | null;
  ai_difficulty_black: AiDifficulty | null;
  ai_difficulty_white: AiDifficulty | null;
  mode: GameMode;
  last_move: { from_row: number; from_col: number; to_row: number; to_col: number } | null;
}

export interface ValidMovesResponse {
  valid_moves: [number, number][];
  enemy_tsuke_moves: [number, number][];
}

export interface ValidArataResponse {
  valid_positions: [number, number][];
}

export type MoveAction = "auto" | "capture" | "tsuke_enemy";
