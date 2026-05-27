"use client";

import { useRef } from "react";
import { Cell as CellType, Piece, Player } from "@/types/game";

const LONG_PRESS_MS = 500;

interface Props {
  cell: CellType;
  row: number;
  col: number;
  isSelected: boolean;
  isHighlighted: boolean;
  isArataHighlight: boolean;
  isEnemyTsuke: boolean;
  isLastMove: boolean;
  currentPlayer: Player;
  gizokuMode: boolean;
  onClick: () => void;
  onLongPress?: () => void; // 長押しでスタック確認（モバイル用）
}

/**
 * セルサイズ:
 *   mobile (< 640px):  w-9  h-9  = 36px  → ボード幅 9×36+24 = 348px
 *   sm     (640px+):   w-11 h-11 = 44px  → ボード幅 9×44+24 = 420px
 *   lg     (1024px+):  w-14 h-14 = 56px  → ボード幅 9×56+24 = 528px
 *
 * 駒は inset-[10%] で自動センタリング（セルの80%のサイズになる）
 */
const CELL = "w-9 h-9 sm:w-11 sm:h-11 lg:w-14 lg:h-14";

// 凝モード用のスタック設定（lg画面専用・56px基準）
const STACK_CFG: Record<number, { size: number; step: number; startTop: number; startLeft: number; fontSize: number }> = {
  1: { size: 44, step: 0,  startTop: 6,  startLeft: 6,  fontSize: 15 },
  2: { size: 28, step: 14, startTop: 4,  startLeft: 4,  fontSize: 11 },
  3: { size: 22, step: 11, startTop: 3,  startLeft: 3,  fontSize: 9  },
};

function getStackPositions(height: number) {
  const cfg = STACK_CFG[height] ?? STACK_CFG[3];
  return Array.from({ length: height }, (_, i) => {
    const steps = height - 1 - i;
    return { top: cfg.startTop + steps * cfg.step, left: cfg.startLeft + steps * cfg.step, size: cfg.size, fontSize: cfg.fontSize };
  });
}

export default function Cell({
  cell, row, col,
  isSelected, isHighlighted, isArataHighlight, isEnemyTsuke,
  isLastMove, gizokuMode, onClick, onLongPress,
}: Props) {
  const stack = cell.stack;
  const height = stack.length;
  const top = stack[height - 1];

  // ── 長押し検出（モバイル向けスタック確認） ────────────────────────────────
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const didLongPress   = useRef(false);

  const handleTouchStart = () => {
    didLongPress.current = false;
    if (!onLongPress) return;
    longPressTimer.current = setTimeout(() => {
      didLongPress.current = true;
      // 触覚フィードバック（対応端末のみ）
      if (typeof navigator !== "undefined" && navigator.vibrate) navigator.vibrate(40);
      onLongPress();
    }, LONG_PRESS_MS);
  };
  const cancelLongPress = () => {
    if (longPressTimer.current) { clearTimeout(longPressTimer.current); longPressTimer.current = null; }
  };
  const handleClick = () => {
    if (didLongPress.current) { didLongPress.current = false; return; } // 長押し後のクリックを無効化
    onClick();
  };

  const squareBg =
    isSelected       ? "bg-yellow-300" :
    isHighlighted    ? "bg-green-200"  :
    isArataHighlight ? "bg-purple-200" :
    isLastMove       ? "bg-sky-200"    :
    (row + col) % 2 === 0 ? "bg-amber-100" : "bg-amber-200";

  const cursor = gizokuMode && height > 0 ? "cursor-zoom-in" : "cursor-pointer";

  const pieceBase =
    top?.owner === "black"
      ? "bg-gray-900 text-white border-gray-700"
      : "bg-white text-gray-900 border-gray-400";

  const heightRing =
    height === 3 ? "ring-2 ring-red-500" :
    height === 2 ? "ring-2 ring-blue-400" : "";

  const enemyOutline = isEnemyTsuke ? "outline outline-2 outline-orange-400" : "";
  const pieceRotate  = top?.owner === "white" ? "rotate-180" : "";

  // ── 通常表示 or 凝モードONで高さ1 or モバイル（lg未満） ─────────────────────
  // lg未満では常にトップ駒のみ表示（凝スタック表示はlg+専用）
  const showNormal = !gizokuMode || height === 0;

  return (
    <div
      className={`relative ${CELL} border border-gray-400 select-none hover:brightness-90 transition-all ${squareBg} ${cursor}`}
      onClick={handleClick}
      onTouchStart={handleTouchStart}
      onTouchEnd={cancelLongPress}
      onTouchMove={cancelLongPress}
    >
      {/* ── 通常ビュー（常にあり） ── */}
      {top && (
        <div
          className={`
            absolute inset-[10%] rounded-full border-2 flex flex-col items-center justify-center
            font-bold shadow-sm ${pieceBase} ${heightRing} ${enemyOutline} ${pieceRotate}
            ${!showNormal ? "lg:hidden" : ""}
          `}
        >
          <span className="text-[10px] sm:text-[12px] lg:text-[15px] leading-none">{top.type}</span>
          {height > 1 && (
            <span className="text-[6px] sm:text-[7px] lg:text-[8px] leading-none opacity-70">{height}</span>
          )}
        </div>
      )}

      {/* 駒なし + ハイライト → 点 */}
      {!top && (isHighlighted || isArataHighlight) && (
        <div
          className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full opacity-50
            ${isArataHighlight ? "bg-purple-500" : "bg-green-500"}`}
        />
      )}

      {/* ── 凝スタック表示（lg以上 & 凝モード & 高さ2以上） ─────────────────── */}
      {!showNormal && height > 0 && (
        <div className="hidden lg:block">
          {stack.map((piece: Piece, idx: number) => {
            const isTopPiece = idx === height - 1;
            const { top: t, left: l, size, fontSize } = getStackPositions(height)[idx];
            const ps = piece.owner === "black"
              ? "bg-gray-900 text-white border-gray-700"
              : "bg-white text-gray-900 border-gray-400";
            const eo = isTopPiece && isEnemyTsuke ? "outline outline-2 outline-orange-400" : "";
            const shadow = isTopPiece ? "shadow-md" : "shadow-sm";
            const rot = piece.owner === "white" ? "rotate-180" : "";
            return (
              <div
                key={idx}
                className={`absolute rounded-full border-2 flex items-center justify-center font-bold ${ps} ${eo} ${shadow} ${rot}`}
                style={{ top: t, left: l, width: size, height: size, fontSize, lineHeight: 1, zIndex: idx + 1 }}
              >
                {piece.type}
              </div>
            );
          })}
        </div>
      )}

      {/* 空マス + ハイライト（凝モード） */}
      {height === 0 && (isHighlighted || isArataHighlight) && (
        <div
          className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full opacity-50 hidden lg:block
            ${isArataHighlight ? "bg-purple-500" : "bg-green-500"}`}
        />
      )}
    </div>
  );
}
