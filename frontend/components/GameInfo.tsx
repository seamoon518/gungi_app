"use client";

import { GameState, Piece, Player, PieceType } from "@/types/game";

interface Props {
  state: GameState;
  selectedHandPiece: PieceType | null;
  gizokuMode: boolean;
  onHandPieceClick: (type: PieceType) => void;
  onGizokuToggle: () => void;
  onNewGame: () => void;
  onResign: () => void;
  error: string | null;
}

const PLAYER_LABEL: Record<Player, string> = { black: "黒陣", white: "白陣" };

function HandPieces({
  pieces,
  player,
  currentPlayer,
  selectedHandPiece,
  onHandPieceClick,
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

  const isCurrentPlayer = player === currentPlayer;

  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {Object.entries(grouped).map(([type, count]) => {
        const isSelected = isCurrentPlayer && selectedHandPiece === type;
        return (
          <button
            key={type}
            onClick={() => isCurrentPlayer && onHandPieceClick(type as PieceType)}
            className={`
              relative inline-flex items-center justify-center
              w-9 h-9 rounded-full border-2 text-xs font-bold transition-all
              ${player === "black" ? "bg-gray-900 text-white border-gray-700" : "bg-white text-gray-900 border-gray-400"}
              ${isSelected ? "ring-4 ring-yellow-400 scale-110" : ""}
              ${isCurrentPlayer ? "cursor-pointer hover:scale-105" : "opacity-50 cursor-default"}
            `}
            title={isCurrentPlayer ? `${type}を打つ` : undefined}
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
  state, selectedHandPiece, gizokuMode,
  onHandPieceClick, onGizokuToggle,
  onNewGame, onResign, error,
}: Props) {
  return (
    <div className="flex flex-col gap-3 p-4 bg-white rounded-lg shadow w-52">
      {/* 手番 / ゲーム終了 */}
      {state.game_over ? (
        <div className="text-center">
          <p className="text-lg font-bold text-red-600">ゲーム終了</p>
          {state.winner
            ? <p className="text-sm mt-1"><span className="font-semibold">{PLAYER_LABEL[state.winner]}</span> の勝利！</p>
            : <p className="text-sm mt-1">千日手（引き分け）</p>
          }
        </div>
      ) : (
        <div className="text-center">
          <p className="text-xs text-gray-500">手番</p>
          <p className="text-xl font-bold mt-1">{PLAYER_LABEL[state.current_player]}</p>
          <p className="text-xs text-gray-400 mt-1">{state.move_count} 手目</p>
        </div>
      )}

      {error && <p className="text-xs text-red-500 text-center break-words">{error}</p>}

      {/* 凝ボタン */}
      <button
        onClick={onGizokuToggle}
        className={`
          w-full py-2 rounded-lg text-sm font-bold border-2 transition-all
          ${gizokuMode
            ? "bg-indigo-600 text-white border-indigo-600"
            : "bg-white text-indigo-600 border-indigo-400 hover:bg-indigo-50"
          }
        `}
        title="凝モード：駒をクリックするとスタックを確認できます"
      >
        {gizokuMode ? "凝モード ON" : "凝"}
      </button>

      {/* 白の手駒 */}
      <div className="border-t pt-2">
        <p className="text-xs font-semibold text-gray-600 mb-1">
          白の手駒
          {state.current_player === "white" && selectedHandPiece && (
            <span className="ml-1 text-yellow-600">（{selectedHandPiece} 選択中）</span>
          )}
        </p>
        <HandPieces
          pieces={state.hand_pieces?.white ?? []}
          player="white"
          currentPlayer={state.current_player}
          selectedHandPiece={selectedHandPiece}
          onHandPieceClick={onHandPieceClick}
        />
      </div>

      {/* 黒の手駒 */}
      <div className="border-t pt-2">
        <p className="text-xs font-semibold text-gray-600 mb-1">
          黒の手駒
          {state.current_player === "black" && selectedHandPiece && (
            <span className="ml-1 text-yellow-600">（{selectedHandPiece} 選択中）</span>
          )}
        </p>
        <HandPieces
          pieces={state.hand_pieces?.black ?? []}
          player="black"
          currentPlayer={state.current_player}
          selectedHandPiece={selectedHandPiece}
          onHandPieceClick={onHandPieceClick}
        />
      </div>

      {/* ボタン群 */}
      <div className="border-t pt-2 flex flex-col gap-2">
        <button onClick={onNewGame} className="px-3 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 transition">
          新規ゲーム
        </button>
        {!state.game_over && (
          <button onClick={onResign} className="px-3 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300 transition">
            投了
          </button>
        )}
      </div>

      {/* 凡例 */}
      <div className="text-xs text-gray-400 border-t pt-2 space-y-0.5">
        <p className="font-semibold">凡例</p>
        <p>緑背景 = 移動可</p>
        <p>紫背景 = 手駒配置可</p>
        <p>橙枠 = ツケも可</p>
        <p>青枠 2段 / 赤枠 3段</p>
      </div>
    </div>
  );
}
