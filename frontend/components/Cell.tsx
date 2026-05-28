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
  isEnemyPreviewCell: boolean;  // プレビュー中の相手駒セル
  isEnemyMovePreview: boolean;  // 相手駒の移動可能先
  currentPlayer: Player;
  gizokuMode: boolean;
  onClick: () => void;
  onLongPress?: () => void; // 長押しでスタック確認（モバイル用）
}

/**
 * セルサイズ:
 *   mobile (< 640px):  w-9  h-9  = 36px
 *   sm     (640px+):   w-11 h-11 = 44px
 *   lg     (1024px+):  w-14 h-14 = 56px
 *
 * 駒は inset-[10%] で自動センタリング（セルの80%のサイズになる）
 */
const CELL = "w-9 h-9 sm:w-11 sm:h-11 lg:w-14 lg:h-14";

/**
 * 凝モード用スタック設定（% 値・全画面サイズ対応）
 * 元の px 値（56px セル基準）をパーセントに換算:
 *   height 1: size=44px→78.6%,  startPos=6px→10.7%,  step=0
 *   height 2: size=28px→50%,    startPos=4px→7.1%,   step=14px→25%
 *   height 3: size=22px→39.3%,  startPos=3px→5.4%,   step=11px→19.6%
 */
const STACK_CFG_PCT: Record<number, { sizePct: number; stepPct: number; startPct: number }> = {
  1: { sizePct: 78.6, stepPct: 0,    startPct: 10.7 },
  2: { sizePct: 50.0, stepPct: 25.0, startPct: 7.1  },
  3: { sizePct: 39.3, stepPct: 19.6, startPct: 5.4  },
};

/** 凝スタック駒のレスポンシブフォントサイズ */
const STACK_FONT_CLASS: Record<number, string> = {
  1: "text-[11px] sm:text-[13px] lg:text-[15px]",
  2: "text-[8px]  sm:text-[10px] lg:text-[11px]",
  3: "text-[7px]  sm:text-[8px]  lg:text-[9px]",
};

function getStackPositionsPct(height: number) {
  const cfg = STACK_CFG_PCT[height] ?? STACK_CFG_PCT[3];
  return Array.from({ length: height }, (_, i) => {
    const steps = height - 1 - i; // 上段ほど steps=0（左上寄り）
    return {
      topPct:  cfg.startPct + steps * cfg.stepPct,
      leftPct: cfg.startPct + steps * cfg.stepPct,
      sizePct: cfg.sizePct,
    };
  });
}

export default function Cell({
  cell, row, col,
  isSelected, isHighlighted, isArataHighlight, isEnemyTsuke,
  isLastMove, isEnemyPreviewCell, isEnemyMovePreview,
  gizokuMode, onClick, onLongPress,
}: Props) {
  const stack = cell.stack;
  const height = stack.length;
  const top = stack[height - 1];

  // ── 長押し検出（モバイル向けスタック確認） ───────────────────────────────
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const didLongPress   = useRef(false);

  const handleTouchStart = () => {
    didLongPress.current = false;
    if (!onLongPress) return;
    longPressTimer.current = setTimeout(() => {
      didLongPress.current = true;
      if (typeof navigator !== "undefined" && navigator.vibrate) navigator.vibrate(40);
      onLongPress();
    }, LONG_PRESS_MS);
  };
  const cancelLongPress = () => {
    if (longPressTimer.current) { clearTimeout(longPressTimer.current); longPressTimer.current = null; }
  };
  const handleClick = () => {
    if (didLongPress.current) { didLongPress.current = false; return; }
    onClick();
  };

  // ── スタイル計算 ──────────────────────────────────────────────────────────
  const squareBg =
    isSelected          ? "bg-yellow-300" :   // 自駒選択中（黄）
    isEnemyPreviewCell  ? "bg-rose-200"   :   // 相手駒プレビュー中（ローズ）
    isHighlighted       ? "bg-green-200"  :   // 自駒の移動可能先（緑）
    isEnemyMovePreview  ? "bg-red-100"    :   // 相手駒の移動可能先（淡赤）
    isArataHighlight    ? "bg-purple-200" :   // 手駒配置可（紫）
    isLastMove          ? "bg-sky-200"    :   // 直前の手（水色）
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

  // 凝モード ON & 駒あり → スタック展開表示（showNormal=false でトップ駒単体表示を隠す）
  const showNormal = !gizokuMode || height === 0;

  return (
    <div
      className={`relative ${CELL} border border-gray-400 select-none hover:brightness-90 transition-all ${squareBg} ${cursor}`}
      onClick={handleClick}
      onTouchStart={handleTouchStart}
      onTouchEnd={cancelLongPress}
      onTouchMove={cancelLongPress}
    >
      {/* ── 通常ビュー（凝モードOFF or 空マス） ── */}
      {top && (
        <div
          className={`
            absolute inset-[10%] rounded-full border-2 flex flex-col items-center justify-center
            font-bold shadow-sm ${pieceBase} ${heightRing} ${enemyOutline} ${pieceRotate}
            ${!showNormal ? "hidden" : ""}
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
      {/* 駒なし + 相手駒の移動可能先 → 赤ドット */}
      {!top && isEnemyMovePreview && !isHighlighted && !isArataHighlight && (
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full opacity-40 bg-red-500" />
      )}

      {/* ── 凝スタック展開表示（凝モードON & 駒あり・全画面サイズ対応） ── */}
      {!showNormal && height > 0 && (
        <>
          {stack.map((piece: Piece, idx: number) => {
            const isTopPiece = idx === height - 1;
            const { topPct, leftPct, sizePct } = getStackPositionsPct(height)[idx];
            const ps = piece.owner === "black"
              ? "bg-gray-900 text-white border-gray-700"
              : "bg-white text-gray-900 border-gray-400";
            const eo = isTopPiece && isEnemyTsuke ? "outline outline-2 outline-orange-400" : "";
            const shadow = isTopPiece ? "shadow-md" : "shadow-sm";
            const rot = piece.owner === "white" ? "rotate-180" : "";
            const fontClass = STACK_FONT_CLASS[height] ?? STACK_FONT_CLASS[3];
            return (
              <div
                key={idx}
                className={`absolute rounded-full border-2 flex items-center justify-center font-bold overflow-hidden
                  ${ps} ${eo} ${shadow} ${rot} ${fontClass}`}
                style={{
                  top:    `${topPct}%`,
                  left:   `${leftPct}%`,
                  width:  `${sizePct}%`,
                  height: `${sizePct}%`,
                  lineHeight: 1,
                  zIndex: idx + 1,
                }}
              >
                {piece.type}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
