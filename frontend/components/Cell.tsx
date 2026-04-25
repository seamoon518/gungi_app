"use client";

import { Cell as CellType, Piece, Player } from "@/types/game";

interface Props {
  cell: CellType;
  row: number;
  col: number;
  isSelected: boolean;
  isHighlighted: boolean;
  isArataHighlight: boolean;
  isEnemyTsuke: boolean;
  currentPlayer: Player;
  gizokuMode: boolean;
  onClick: () => void;
}

// Cell is w-14 h-14 = 56px × 56px

/** Single piece (凝 OFF): large centered circle */
const SINGLE_SIZE = 44;

/** Stack display (凝 ON): smaller pieces with overlap for 3D depth */
const STACK_CONFIG: Record<number, { size: number; step: number; startTop: number; startLeft: number; fontSize: number }> = {
  1: { size: 44, step: 0,  startTop: 6,  startLeft: 6,  fontSize: 15 },
  2: { size: 28, step: 14, startTop: 4,  startLeft: 4,  fontSize: 11 },
  3: { size: 22, step: 11, startTop: 3,  startLeft: 3,  fontSize: 9  },
};

/**
 * Compute positions for each piece in stack when 凝 mode is ON.
 * idx=height-1 (top piece)  → top-left (smallest offset, visually highest)
 * idx=0        (bottom piece)→ bottom-right (largest offset, visually lowest)
 */
function getStackPositions(height: number): { top: number; left: number; size: number; fontSize: number }[] {
  const cfg = STACK_CONFIG[height] ?? STACK_CONFIG[3];
  return Array.from({ length: height }, (_, i) => {
    // i=0 is bottom, i=height-1 is top
    const steps = height - 1 - i; // top gets 0 extra steps, bottom gets most
    return {
      top: cfg.startTop + steps * cfg.step,
      left: cfg.startLeft + steps * cfg.step,
      size: cfg.size,
      fontSize: cfg.fontSize,
    };
  });
}

export default function Cell({
  cell, row, col,
  isSelected, isHighlighted, isArataHighlight, isEnemyTsuke,
  gizokuMode,
  onClick,
}: Props) {
  const stack = cell.stack;
  const height = stack.length;
  const top = stack[height - 1];

  const squareBg = isSelected
    ? "bg-yellow-300"
    : isHighlighted
    ? "bg-green-200"
    : isArataHighlight
    ? "bg-purple-200"
    : (row + col) % 2 === 0
    ? "bg-amber-100"
    : "bg-amber-200";

  const cursor = gizokuMode && height > 0 ? "cursor-zoom-in" : "cursor-pointer";

  // ── 凝 mode OFF: show only top piece (original look) ──────────────
  if (!gizokuMode || height === 0) {
    const topOffset = (56 - SINGLE_SIZE) / 2; // = 6

    const pieceStyle =
      top?.owner === "black"
        ? "bg-gray-900 text-white border-gray-700"
        : "bg-white text-gray-900 border-gray-400";

    const heightRing =
      height === 3 ? "ring-2 ring-red-500" :
      height === 2 ? "ring-2 ring-blue-400" : "";

    const enemyOutline = isEnemyTsuke ? "outline outline-2 outline-orange-400" : "";

    return (
      <div
        className={`relative w-14 h-14 border border-gray-400 select-none hover:brightness-90 transition-all ${squareBg} ${cursor}`}
        onClick={onClick}
      >
        {top ? (
          <div
            className={`absolute rounded-full border-2 flex flex-col items-center justify-center font-bold shadow-sm ${pieceStyle} ${heightRing} ${enemyOutline}`}
            style={{ top: topOffset, left: topOffset, width: SINGLE_SIZE, height: SINGLE_SIZE }}
          >
            <span style={{ fontSize: 15, lineHeight: 1 }}>{top.type}</span>
            {height > 1 && (
              <span style={{ fontSize: 8, lineHeight: 1, opacity: 0.7 }}>{height}</span>
            )}
          </div>
        ) : (isHighlighted || isArataHighlight) ? (
          <div
            className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-4 h-4 rounded-full opacity-50 ${isArataHighlight ? "bg-purple-500" : "bg-green-500"}`}
          />
        ) : null}
      </div>
    );
  }

  // ── 凝 mode ON: show all pieces overlapping diagonally ────────────
  const positions = getStackPositions(height);

  return (
    <div
      className={`relative w-14 h-14 border border-gray-400 select-none hover:brightness-90 transition-all ${squareBg} ${cursor}`}
      onClick={onClick}
    >
      {stack.map((piece: Piece, idx: number) => {
        const isTopPiece = idx === height - 1;
        const { top: t, left: l, size, fontSize } = positions[idx];

        const pieceStyle =
          piece.owner === "black"
            ? "bg-gray-900 text-white border-gray-700"
            : "bg-white text-gray-900 border-gray-400";

        const enemyOutline = isTopPiece && isEnemyTsuke
          ? "outline outline-2 outline-orange-400"
          : "";

        // Subtle shadow to enhance depth: bottom pieces darker shadow
        const shadow = isTopPiece ? "shadow-md" : "shadow-sm";

        return (
          <div
            key={idx}
            className={`absolute rounded-full border-2 flex items-center justify-center font-bold ${pieceStyle} ${enemyOutline} ${shadow}`}
            style={{
              top: t,
              left: l,
              width: size,
              height: size,
              fontSize,
              lineHeight: 1,
              zIndex: idx + 1,
            }}
          >
            {piece.type}
          </div>
        );
      })}

      {height === 0 && (isHighlighted || isArataHighlight) && (
        <div
          className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-4 h-4 rounded-full opacity-50 ${isArataHighlight ? "bg-purple-500" : "bg-green-500"}`}
        />
      )}
    </div>
  );
}
