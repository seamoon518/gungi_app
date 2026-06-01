"use client";

import { GameState, Player } from "@/types/game";
import Cell from "./Cell";

interface Props {
  state: GameState;
  selectedCell: [number, number] | null;
  highlights: [number, number][];
  enemyTsukeMoves: [number, number][];
  arataHighlights: [number, number][];
  lastMoveHighlights: [number, number][];
  gizokuMode: boolean;
  onCellClick: (row: number, col: number) => void;
  onCellLongPress: (row: number, col: number) => void; // 長押しでスタック確認（モバイル用）
  enemyPreviewCell: [number, number] | null;  // 相手駒プレビュー中のセル
  enemyPreviewMoves: [number, number][];       // 相手駒の移動可能範囲
  flipped?: boolean;  // true → 盤を 180°反転（後手視点）
}

export default function Board({
  state, selectedCell, highlights, enemyTsukeMoves,
  arataHighlights, lastMoveHighlights, gizokuMode, onCellClick, onCellLongPress,
  enemyPreviewCell, enemyPreviewMoves, flipped = false,
}: Props) {
  const highlightSet = new Set(highlights.map(([r, c]) => `${r},${c}`));
  const enemyTsukeSet = new Set(enemyTsukeMoves.map(([r, c]) => `${r},${c}`));
  const arataSet = new Set(arataHighlights.map(([r, c]) => `${r},${c}`));
  const lastMoveSet = new Set(lastMoveHighlights.map(([r, c]) => `${r},${c}`));
  const enemyPreviewMoveSet = new Set(enemyPreviewMoves.map(([r, c]) => `${r},${c}`));

  // flipped=true: コンテナを 180° 回転（後手視点）
  // ラベルはさらに 180° 反転して読みやすくする
  // セル内の駒は既存の rotate-180 と合成され自動的に正しい向きになる
  const containerClass = `flex flex-col items-center${flipped ? " rotate-180" : ""}`;
  const labelClass = flipped ? "rotate-180" : "";

  return (
    <div className={containerClass}>
      <div className="flex">
        <div className="w-6" />
        {Array.from({ length: 9 }, (_, c) => (
          <div key={c} className={`w-9 sm:w-11 lg:w-14 text-center text-[9px] sm:text-[10px] lg:text-xs text-gray-500 mb-1 ${labelClass}`}>
            {c + 1}
          </div>
        ))}
      </div>
      {state.board.map((row, r) => (
        <div key={r} className="flex items-center">
          <div className={`w-5 lg:w-6 text-[9px] lg:text-xs text-gray-500 text-right pr-1 ${labelClass}`}>{r + 1}</div>
          {row.map((cell, c) => (
            <Cell
              key={c}
              cell={cell}
              row={r}
              col={c}
              isSelected={selectedCell !== null && selectedCell[0] === r && selectedCell[1] === c}
              isHighlighted={highlightSet.has(`${r},${c}`)}
              isArataHighlight={arataSet.has(`${r},${c}`)}
              isEnemyTsuke={enemyTsukeSet.has(`${r},${c}`)}
              isLastMove={lastMoveSet.has(`${r},${c}`)}
              isEnemyPreviewCell={enemyPreviewCell !== null && enemyPreviewCell[0] === r && enemyPreviewCell[1] === c}
              isEnemyMovePreview={enemyPreviewMoveSet.has(`${r},${c}`)}
              currentPlayer={state.current_player}
              gizokuMode={gizokuMode}
              onClick={() => onCellClick(r, c)}
              onLongPress={() => onCellLongPress(r, c)}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
