"use client";

import { GameState, Player } from "@/types/game";
import Cell from "./Cell";

interface Props {
  state: GameState;
  selectedCell: [number, number] | null;
  highlights: [number, number][];
  enemyTsukeMoves: [number, number][];
  arataHighlights: [number, number][];
  gizokuMode: boolean;
  onCellClick: (row: number, col: number) => void;
}

export default function Board({
  state, selectedCell, highlights, enemyTsukeMoves,
  arataHighlights, gizokuMode, onCellClick,
}: Props) {
  const highlightSet = new Set(highlights.map(([r, c]) => `${r},${c}`));
  const enemyTsukeSet = new Set(enemyTsukeMoves.map(([r, c]) => `${r},${c}`));
  const arataSet = new Set(arataHighlights.map(([r, c]) => `${r},${c}`));

  return (
    <div className="flex flex-col items-center">
      <div className="flex">
        <div className="w-6" />
        {Array.from({ length: 9 }, (_, c) => (
          <div key={c} className="w-14 text-center text-xs text-gray-500 mb-1">{c + 1}</div>
        ))}
      </div>
      {state.board.map((row, r) => (
        <div key={r} className="flex items-center">
          <div className="w-6 text-xs text-gray-500 text-right pr-1">{r + 1}</div>
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
              currentPlayer={state.current_player}
              gizokuMode={gizokuMode}
              onClick={() => onCellClick(r, c)}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
