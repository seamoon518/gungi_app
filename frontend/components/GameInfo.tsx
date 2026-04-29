"use client";

import { GameState, Piece, Player, PieceType } from "@/types/game";

interface Props {
  state: GameState;
  player: Player;              // このパネルが担当するプレイヤー
  flipped?: boolean;           // true → 180°回転（白陣側パネル用）
  selectedHandPiece: PieceType | null;
  gizokuMode: boolean;
  onHandPieceClick: (type: PieceType) => void;
  onGizokuToggle: () => void;
  onResign: () => void;
  onSetupDone?: () => void;    // 済を宣言（setup phaseのみ）
  error?: string | null;
}

const PLAYER_LABEL: Record<Player, string> = { black: "黒陣", white: "白陣" };

function HandPieces({
  pieces, player, currentPlayer, selectedHandPiece, onHandPieceClick,
}: {
  pieces: Piece[];
  player: Player;
  currentPlayer: Player;
  selectedHandPiece: PieceType | null;
  onHandPieceClick: (type: PieceType) => void;
}) {
  if (pieces.length === 0) return <p className="text-xs text-gray-400">なし</p>;

  const grouped: Record<string, number> = {};
  for (const p of pieces) grouped[p.type] = (grouped[p.type] ?? 0) + 1;

  const isActive = player === currentPlayer;

  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {Object.entries(grouped).map(([type, count]) => {
        const isSelected = isActive && selectedHandPiece === type;
        return (
          <button
            key={type}
            onClick={() => isActive && onHandPieceClick(type as PieceType)}
            className={`
              relative inline-flex items-center justify-center
              w-9 h-9 rounded-full border-2 text-xs font-bold transition-all
              ${player === "black" ? "bg-gray-900 text-white border-gray-700" : "bg-white text-gray-900 border-gray-400"}
              ${isSelected ? "ring-4 ring-yellow-400 scale-110" : ""}
              ${isActive ? "cursor-pointer hover:scale-105" : "opacity-50 cursor-default"}
            `}
          >
            {type}
            {count > 1 && (
              <span className="absolute -top-1 -right-1 bg-blue-500 text-white text-[9px] rounded-full w-3.5 h-3.5 flex items-center justify-center">
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default function GameInfo({
  state, player, flipped = false,
  selectedHandPiece, gizokuMode,
  onHandPieceClick, onGizokuToggle,
  onResign, onSetupDone, error,
}: Props) {
  const isActive = state.current_player === player;
  const isSetup = state.phase === "setup";
  const isAiControlled = state.ai_player === player;

  const panel = (
    <div className="flex flex-col gap-2 p-3 bg-white rounded-xl shadow w-44">

      {/* プレイヤー名 + 手番表示 */}
      <div className="text-center">
        <p className={`text-base font-bold ${isActive && !state.game_over ? "text-blue-600" : "text-gray-600"}`}>
          {PLAYER_LABEL[player]}
          {isAiControlled && (
            <span className="ml-1 text-xs text-amber-600 font-normal">（AI）</span>
          )}
        </p>
        {!state.game_over && (
          <p className={`text-[10px] mt-0.5 ${isActive ? "text-blue-400 font-semibold" : "text-gray-300"}`}>
            {isActive
              ? isAiControlled
                ? "AI 思考中..."
                : (isSetup ? "配置中" : "▶ 手番")
              : "待機中"}
          </p>
        )}
        {state.game_over && state.winner === player && (
          <p className="text-xs text-green-600 font-bold mt-0.5">勝利！</p>
        )}
      </div>

      {/* エラー */}
      {isActive && error && (
        <p className="text-[10px] text-red-500 text-center break-words">{error}</p>
      )}

      {/* 手駒 */}
      <div className="border-t pt-2">
        <p className="text-xs font-semibold text-gray-500 mb-1">
          手駒
          {isActive && !isAiControlled && selectedHandPiece && (
            <span className="ml-1 text-yellow-600">（{selectedHandPiece}）</span>
          )}
        </p>
        <HandPieces
          pieces={state.hand_pieces?.[player] ?? []}
          player={player}
          currentPlayer={isAiControlled ? "black" : state.current_player}
          selectedHandPiece={isAiControlled ? null : selectedHandPiece}
          onHandPieceClick={isAiControlled ? () => {} : onHandPieceClick}
        />
      </div>

      {/* ボタン群 */}
      <div className="border-t pt-2 flex flex-col gap-1.5">
        {/* 凝ボタン（AI側でも閲覧用に使える） */}
        <button
          onClick={onGizokuToggle}
          className={`
            w-full py-1.5 rounded-lg text-xs font-bold border-2 transition-all
            ${gizokuMode
              ? "bg-indigo-600 text-white border-indigo-600"
              : "bg-white text-indigo-600 border-indigo-400 hover:bg-indigo-50"
            }
          `}
        >
          {gizokuMode ? "凝 ON" : "凝"}
        </button>

        {/* 済を宣言（setupフェーズ・自分のターン・人間のみ） */}
        {isSetup && isActive && !isAiControlled && onSetupDone && !state.game_over && (
          <button
            onClick={onSetupDone}
            className="w-full py-1.5 bg-green-600 text-white text-xs font-bold rounded-lg hover:bg-green-700 transition"
          >
            済を宣言
          </button>
        )}

        {/* 投了（playフェーズ・自分のターン・人間のみ） */}
        {!isSetup && isActive && !isAiControlled && !state.game_over && (
          <button
            onClick={onResign}
            className="w-full py-1.5 bg-gray-200 text-gray-700 text-xs rounded-lg hover:bg-gray-300 transition"
          >
            投了
          </button>
        )}
      </div>

      {/* 凡例（コンパクト） */}
      <div className="text-[9px] text-gray-400 border-t pt-1.5 space-y-0.5">
        <p>緑=移動可 紫=手駒配置 橙=ツケ可</p>
        <p>青枠=2段 赤枠=3段</p>
      </div>
    </div>
  );

  if (!flipped) return panel;

  // 白陣パネルは180°回転して相手側から読めるようにする
  return (
    <div className="rotate-180">
      {panel}
    </div>
  );
}
