export type Player = "black" | "white";

export type PieceType =
  | "帥" | "大" | "中" | "小" | "侍"
  | "槍" | "馬" | "忍" | "砦" | "兵"
  | "砲" | "筒" | "弓" | "謀";

export type GameLevel = "nyumon" | "shokyuu" | "chukyuu" | "joukyuu";
export type GameMode = "pvp" | "ai";
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
}

export interface ValidMovesResponse {
  valid_moves: [number, number][];
  enemy_tsuke_moves: [number, number][];
}

export interface ValidArataResponse {
  valid_positions: [number, number][];
}

export type MoveAction = "auto" | "capture" | "tsuke_enemy";
