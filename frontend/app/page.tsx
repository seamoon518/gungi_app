"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  GameState, MoveAction, Piece, PieceType,
  Player, GameLevel, GameMode, AiDifficulty,
} from "@/types/game";
import { api } from "@/lib/api";
import Board from "@/components/Board";
import GameInfo from "@/components/GameInfo";

type Screen =
  | "title"
  | "mode_select"
  | "pvp_rule_select"
  | "ai_difficulty_select"
  | "ai_rule_select"
  | "game";

interface PendingChoice {
  fromRow: number; fromCol: number; toRow: number; toCol: number;
}

const LEVEL_INFO: {
  key: GameLevel;
  label: string;
  placement: string;
  special: string;
  tsuke: string;
  suiTsuke: string;
}[] = [
  { key: "nyumon",  label: "入門編", placement: "確定", special: "なし",   tsuke: "二段", suiTsuke: "なし" },
  { key: "shokyuu", label: "初級編", placement: "確定", special: "弓のみ", tsuke: "二段", suiTsuke: "なし" },
  { key: "chukyuu", label: "中級編", placement: "自由", special: "あり",   tsuke: "二段", suiTsuke: "あり" },
  { key: "joukyuu", label: "上級編", placement: "自由", special: "あり",   tsuke: "三段", suiTsuke: "あり" },
];

function isSuiPlaced(state: GameState, player: Player): boolean {
  for (const row of state.board)
    for (const cell of row)
      if (cell.stack.some(p => p.type === "帥" && p.owner === player)) return true;
  return false;
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("title");
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [gameMode, setGameMode] = useState<GameMode>("pvp");
  const [aiDifficulty, setAiDifficulty] = useState<AiDifficulty>("easy");

  const [selectedCell, setSelectedCell] = useState<[number, number] | null>(null);
  const [highlights, setHighlights] = useState<[number, number][]>([]);
  const [enemyTsukeMoves, setEnemyTsukeMoves] = useState<[number, number][]>([]);
  const [pendingChoice, setPendingChoice] = useState<PendingChoice | null>(null);

  const [selectedHandPiece, setSelectedHandPiece] = useState<PieceType | null>(null);
  const [arataHighlights, setArataHighlights] = useState<[number, number][]>([]);

  const [gizokuMode, setGizokuMode] = useState(false);
  const [inspectStack, setInspectStack] = useState<Piece[] | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showHomeConfirm, setShowHomeConfirm] = useState(false);

  const clearAll = () => {
    setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]);
    setPendingChoice(null); setSelectedHandPiece(null); setArataHighlights([]);
    setGizokuMode(false); setInspectStack(null); setError(null);
  };

  // AI の手番を自動トリガー
  const aiTriggeringRef = useRef(false);
  useEffect(() => {
    if (!gameState) return;
    if (gameState.game_over) return;
    if (gameState.mode !== "ai") return;
    if (!gameState.ai_player) return;
    if (gameState.current_player !== gameState.ai_player) return;
    if (aiTriggeringRef.current) return;

    aiTriggeringRef.current = true;
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const state = await api.aiMove(gameState.game_id);
        setGameState(state);
        clearAll();
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
        aiTriggeringRef.current = false;
      }
    }, 400);  // 少し待ってから思考（UX向上）

    return () => {
      clearTimeout(timer);
      aiTriggeringRef.current = false;
    };
  }, [gameState?.game_id, gameState?.current_player, gameState?.game_over]);

  const handleSelectLevel = useCallback(async (level: GameLevel) => {
    setLoading(true); setError(null);
    try {
      const state = await api.newGame(level, gameMode, gameMode === "ai" ? aiDifficulty : undefined);
      setGameState(state); clearAll(); setScreen("game");
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameMode, aiDifficulty]);

  const handleResign = useCallback(async () => {
    if (!gameState) return;
    setLoading(true);
    try {
      const state = await api.resign(gameState.game_id);
      setGameState(state); clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState]);

  const executeMove = useCallback(async (
    fromRow: number, fromCol: number, toRow: number, toCol: number, action: MoveAction
  ) => {
    if (!gameState) return;
    setLoading(true); setPendingChoice(null);
    try {
      const state = await api.move(gameState.game_id, fromRow, fromCol, toRow, toCol, action);
      setGameState(state); clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState]);

  const executeArata = useCallback(async (toRow: number, toCol: number) => {
    if (!gameState || !selectedHandPiece) return;
    setLoading(true);
    try {
      const state = await api.arata(gameState.game_id, selectedHandPiece, toRow, toCol);
      setGameState(state); clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState, selectedHandPiece]);

  const executeSetupPlace = useCallback(async (toRow: number, toCol: number) => {
    if (!gameState || !selectedHandPiece) return;
    setLoading(true);
    try {
      const state = await api.setupPlace(gameState.game_id, selectedHandPiece, toRow, toCol);
      setGameState(state); clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState, selectedHandPiece]);

  const handleSetupDone = useCallback(async () => {
    if (!gameState || loading) return;
    setLoading(true);
    try {
      const state = await api.setupDone(gameState.game_id);
      setGameState(state); clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState, loading]);

  const handleHandPieceClick = useCallback(async (type: PieceType) => {
    if (!gameState || loading) return;
    setError(null);
    if (selectedHandPiece === type) {
      setSelectedHandPiece(null); setArataHighlights([]); return;
    }
    if (gameState.phase === "setup") {
      const suiOnBoard = isSuiPlaced(gameState, gameState.current_player);
      if (!suiOnBoard && type !== "帥") { setError("帥を先に配置してください。"); return; }
    }
    setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]);
    setSelectedHandPiece(type);
    setLoading(true);
    try {
      const endpoint = gameState.phase === "setup"
        ? api.getValidSetupPositions(gameState.game_id)
        : api.getValidArata(gameState.game_id);
      const { valid_positions } = await endpoint;
      setArataHighlights(valid_positions as [number, number][]);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState, selectedHandPiece, loading]);

  const handleCellClick = useCallback(async (row: number, col: number) => {
    if (!gameState || gameState.game_over || loading) return;
    setError(null);

    if (gizokuMode) {
      const stack = gameState.board[row][col].stack;
      setInspectStack(stack.length > 0 ? stack : null);
      return;
    }

    if (gameState.phase === "setup") {
      if (selectedHandPiece) {
        const isValid = arataHighlights.some(([r, c]) => r === row && c === col);
        if (isValid) { await executeSetupPlace(row, col); }
        else { setSelectedHandPiece(null); setArataHighlights([]); }
      }
      return;
    }

    if (selectedHandPiece) {
      const isValid = arataHighlights.some(([r, c]) => r === row && c === col);
      if (isValid) { await executeArata(row, col); }
      else { setSelectedHandPiece(null); setArataHighlights([]); }
      return;
    }

    if (selectedCell && highlights.some(([r, c]) => r === row && c === col)) {
      const isEnemyTsuke = enemyTsukeMoves.some(([r, c]) => r === row && c === col);
      const destStack = gameState.board[row][col].stack;
      const destIsEnemy = destStack.length > 0 && destStack[destStack.length - 1].owner !== gameState.current_player;
      if (isEnemyTsuke && destIsEnemy) {
        setPendingChoice({ fromRow: selectedCell[0], fromCol: selectedCell[1], toRow: row, toCol: col });
      } else {
        await executeMove(selectedCell[0], selectedCell[1], row, col, "auto");
      }
      return;
    }

    if (selectedCell && selectedCell[0] === row && selectedCell[1] === col) {
      setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]); return;
    }

    const stack = gameState.board[row][col].stack;
    if (!stack.length) { setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]); return; }
    const topPiece = stack[stack.length - 1];
    if (topPiece.owner !== gameState.current_player) { setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]); return; }

    setLoading(true);
    try {
      const { valid_moves, enemy_tsuke_moves } = await api.getValidMoves(gameState.game_id, row, col);
      setSelectedCell([row, col]);
      setHighlights(valid_moves as [number, number][]);
      setEnemyTsukeMoves(enemy_tsuke_moves as [number, number][]);
      setSelectedHandPiece(null); setArataHighlights([]);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [
    gameState, selectedCell, highlights, enemyTsukeMoves,
    selectedHandPiece, arataHighlights, gizokuMode, loading,
    executeMove, executeArata, executeSetupPlace,
  ]);

  // ─── 共通: ホームボタン・確認モーダル・最終手ハイライト ──────────────
  const lastMoveHighlights: [number, number][] = (() => {
    const lm = gameState?.last_move;
    if (!lm) return [];
    const cells: [number, number][] = [[lm.to_row, lm.to_col]];
    if (lm.from_row >= 0) cells.push([lm.from_row, lm.from_col]);
    return cells;
  })();

  const homeBtn = (
    <button
      onClick={() => setShowHomeConfirm(true)}
      className="fixed top-3 right-3 z-40 px-3 py-1.5 bg-white/90 backdrop-blur-sm border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-gray-800 hover:bg-white hover:border-gray-300 shadow-sm transition"
    >
      ← ホーム
    </button>
  );

  const homeConfirmModal = showHomeConfirm ? (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[60]">
      <div className="bg-white rounded-2xl shadow-xl p-6 w-72 flex flex-col gap-4">
        <p className="text-center font-bold text-gray-800">タイトルに戻りますか？</p>
        <p className="text-center text-sm text-gray-500">
          {screen === "game" && gameState && !gameState.game_over
            ? "対局が中断されます。進捗は保存されません。"
            : "タイトル画面に移動します。"}
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => setShowHomeConfirm(false)}
            className="flex-1 py-2.5 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 text-sm font-medium"
          >
            キャンセル
          </button>
          <button
            onClick={() => { setShowHomeConfirm(false); setScreen("title"); setGameState(null); clearAll(); }}
            className="flex-1 py-2.5 bg-red-500 text-white rounded-lg hover:bg-red-600 text-sm font-medium"
          >
            戻る
          </button>
        </div>
      </div>
    </div>
  ) : null;

  // ─── ルール選択画面（PvP/AI 共通） ──────────────────────────────────
  const renderRuleSelect = (backScreen: Screen) => (
    <>
    <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-5 p-4">
      <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍議</h1>
      <p className="text-lg text-gray-600">どのルールで遊びますか？</p>
      <div className="flex flex-col gap-3 w-full max-w-md">
        {LEVEL_INFO.map(({ key, label, placement, special, tsuke, suiTsuke }) => (
          <button
            key={key}
            onClick={() => handleSelectLevel(key)}
            disabled={loading}
            className="flex flex-col items-stretch text-left rounded-xl overflow-hidden border-2 border-blue-400 hover:border-blue-600 hover:shadow-lg transition disabled:opacity-50 focus:outline-none"
          >
            <div className="bg-blue-600 text-white px-4 py-2 font-bold text-base">{label}</div>
            <div className="bg-white px-4 py-3">
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-gray-700">
                <div><span className="text-gray-400">初期配置：</span><span className="font-medium">{placement}</span></div>
                <div><span className="text-gray-400">特殊駒：</span><span className="font-medium">{special}</span></div>
                <div><span className="text-gray-400">ツケ：</span><span className="font-medium">{tsuke}</span></div>
                <div><span className="text-gray-400">師ツケ：</span><span className="font-medium">{suiTsuke}</span></div>
              </div>
            </div>
          </button>
        ))}
      </div>
      <button onClick={() => setScreen(backScreen)} className="text-sm text-gray-400 hover:text-gray-600 underline mt-1">← 戻る</button>
      {error && <p className="text-red-500 text-sm">{error}</p>}
    </main>
    {homeBtn}{homeConfirmModal}
    </>
  );

  // ─── Screens ────────────────────────────────────────────────────────

  if (screen === "title") {
    return (
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8 p-4">
        <h1 className="text-4xl sm:text-5xl font-bold tracking-widest text-gray-800">軍議</h1>
        <p className="text-gray-500 text-sm">HUNTER×HUNTER の思考型ボードゲーム</p>
        <button
          onClick={() => setScreen("mode_select")}
          className="px-10 py-4 bg-blue-600 text-white text-xl rounded-xl hover:bg-blue-700 transition shadow-lg"
        >
          ゲームを始める
        </button>
      </main>
    );
  }

  if (screen === "mode_select") {
    return (
      <>
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8 p-4">
        <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍議</h1>
        <p className="text-lg text-gray-600">対戦モードを選択してください</p>
        <div className="flex flex-col gap-4 w-full max-w-xs">
          <button
            onClick={() => { setGameMode("pvp"); setScreen("pvp_rule_select"); }}
            className="flex flex-col items-start px-6 py-5 bg-white border-2 border-blue-500 rounded-xl hover:bg-blue-50 transition shadow"
          >
            <span className="text-lg font-bold text-blue-700">プレイヤー同士で対戦</span>
            <span className="text-xs text-gray-500 mt-1">同じ画面で2人対戦します</span>
          </button>
          <button
            onClick={() => { setGameMode("ai"); setScreen("ai_difficulty_select"); }}
            className="flex flex-col items-start px-6 py-5 bg-white border-2 border-amber-500 rounded-xl hover:bg-amber-50 transition shadow"
          >
            <span className="text-lg font-bold text-amber-700">AIと対戦</span>
            <span className="text-xs text-gray-500 mt-1">コンピューターと対戦します（α版）</span>
          </button>
        </div>
      </main>
      {homeBtn}{homeConfirmModal}
    </>
    );
  }

  if (screen === "pvp_rule_select") return renderRuleSelect("mode_select");

  if (screen === "ai_difficulty_select") {
    return (
      <>
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8 p-4">
        <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍議</h1>
        <p className="text-lg text-gray-600">誰と対戦しますか？</p>
        <div className="flex flex-col gap-4 w-full max-w-xs">
          {(["easy", "normal", "hard"] as AiDifficulty[]).map((diff) => {
            const label = diff === "easy" ? "簡単" : diff === "normal" ? "普通" : "難しい";
            return (
              <button key={diff} onClick={() => { setAiDifficulty(diff); setScreen("ai_rule_select"); }}
                className="px-6 py-4 bg-white border-2 border-amber-500 rounded-xl hover:bg-amber-50 transition shadow font-bold text-amber-700 text-lg">
                {label}
              </button>
            );
          })}
        </div>
        <button onClick={() => setScreen("mode_select")} className="text-sm text-gray-400 hover:text-gray-600 underline">← 戻る</button>
      </main>
      {homeBtn}{homeConfirmModal}
      </>
    );
  }

  if (screen === "ai_rule_select") return renderRuleSelect("ai_difficulty_select");

  // ─── ゲーム画面 ─────────────────────────────────────────────────────
  return (
    <>
    <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center p-2 sm:p-4 gap-3">
      <h1 className="text-xl sm:text-2xl font-bold tracking-widest text-gray-800">軍議</h1>

      {gameState && (
        <>
          {/* ゲームオーバー表示 */}
          {gameState.game_over && (
            <div className="text-center bg-white rounded-xl shadow px-6 py-3">
              <p className="text-lg font-bold text-red-600">ゲーム終了</p>
              {gameState.winner
                ? <p className="text-sm mt-1"><span className="font-semibold">{gameState.winner === "black" ? "黒陣" : "白陣"}</span> の勝利！</p>
                : <p className="text-sm mt-1">千日手（引き分け）</p>
              }
            </div>
          )}

          {/* setup フェーズバナー */}
          {gameState.phase === "setup" && (
            <div className="bg-yellow-50 border-2 border-yellow-400 rounded-xl p-3 text-sm w-full max-w-lg">
              <p className="font-bold text-yellow-800 text-base mb-1">初期配置フェーズ</p>
              <p className="text-yellow-700 mb-2">
                {!isSuiPlaced(gameState, gameState.current_player)
                  ? "まず帥（スイ）を自陣に配置してください"
                  : "駒を選んで自陣（3列目まで）に配置してください"}
              </p>
              <div className="flex gap-4 text-xs font-medium">
                <span className={`px-2 py-0.5 rounded-full border ${gameState.setup_done.black ? "bg-green-100 border-green-400 text-green-700" : "bg-gray-100 border-gray-300 text-gray-500"}`}>
                  黒: {gameState.setup_done.black ? "済 ✓" : "配置中..."}
                </span>
                <span className={`px-2 py-0.5 rounded-full border ${gameState.setup_done.white ? "bg-green-100 border-green-400 text-green-700" : "bg-gray-100 border-gray-300 text-gray-500"}`}>
                  白: {gameState.setup_done.white ? "済 ✓" : "配置中..."}
                </span>
              </div>
            </div>
          )}

          {/*
            レイアウト:
            ・スマホ（縦）: 白パネル(上,反転) → ボード → 黒パネル(下)
            ・PC（横）:     白パネル(左,反転) | ボード | 黒パネル(右)
          */}
          <div className="flex flex-col lg:flex-row items-center lg:items-start gap-3">

            {/* 白陣パネル（180°回転） */}
            <GameInfo
              state={gameState}
              player="white"
              flipped={true}
              selectedHandPiece={gameState.current_player === "white" ? selectedHandPiece : null}
              gizokuMode={gizokuMode}
              onHandPieceClick={handleHandPieceClick}
              onGizokuToggle={() => { setGizokuMode(v => !v); setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]); setSelectedHandPiece(null); setArataHighlights([]); setInspectStack(null); }}
              onResign={handleResign}
              onSetupDone={handleSetupDone}
              error={gameState.current_player === "white" ? error : null}
            />

            {/* ボード（横スクロール対応） */}
            <div className="overflow-x-auto">
              <Board
                state={gameState}
                selectedCell={selectedCell}
                highlights={highlights}
                enemyTsukeMoves={enemyTsukeMoves}
                arataHighlights={arataHighlights}
                lastMoveHighlights={lastMoveHighlights}
                gizokuMode={gizokuMode}
                onCellClick={handleCellClick}
              />
            </div>

            {/* 黒陣パネル（通常） */}
            <GameInfo
              state={gameState}
              player="black"
              flipped={false}
              selectedHandPiece={gameState.current_player === "black" ? selectedHandPiece : null}
              gizokuMode={gizokuMode}
              onHandPieceClick={handleHandPieceClick}
              onGizokuToggle={() => { setGizokuMode(v => !v); setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]); setSelectedHandPiece(null); setArataHighlights([]); setInspectStack(null); }}
              onResign={handleResign}
              onSetupDone={handleSetupDone}
              error={gameState.current_player === "black" ? error : null}
            />
          </div>
        </>
      )}

      {/* 取る or ツケる 選択モーダル */}
      {pendingChoice && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl p-6 w-72 flex flex-col gap-4">
            <p className="text-center font-bold text-gray-800">どうしますか？</p>
            <p className="text-center text-sm text-gray-500">相手の駒の上に移動します</p>
            <button onClick={() => executeMove(pendingChoice.fromRow, pendingChoice.fromCol, pendingChoice.toRow, pendingChoice.toCol, "capture")}
              className="py-3 bg-red-600 text-white font-bold rounded-lg hover:bg-red-700 transition">取る（敵駒を除去）</button>
            <button onClick={() => executeMove(pendingChoice.fromRow, pendingChoice.fromCol, pendingChoice.toRow, pendingChoice.toCol, "tsuke_enemy")}
              className="py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 transition">ツケる（重ねる）</button>
            <button onClick={() => setPendingChoice(null)} className="py-2 text-gray-500 text-sm hover:text-gray-800">キャンセル</button>
          </div>
        </div>
      )}

      {/* 凝 スタック確認モーダル */}
      {gizokuMode && inspectStack !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setInspectStack(null)}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-64 flex flex-col gap-3" onClick={e => e.stopPropagation()}>
            <p className="text-center font-bold text-gray-800">凝 — スタック確認</p>
            {inspectStack.length === 0 ? (
              <p className="text-center text-gray-400 text-sm">このマスは空です</p>
            ) : (
              <div className="flex flex-col gap-2">
                {[...inspectStack].reverse().map((piece, i) => (
                  <div key={i} className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${piece.owner === "black" ? "bg-gray-900 text-white border-gray-700" : "bg-white text-gray-900 border-gray-300"}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border ${piece.owner === "black" ? "bg-gray-800 text-white border-gray-600" : "bg-gray-50 text-gray-900 border-gray-400"}`}>
                      {piece.type}
                    </div>
                    <div>
                      <p className="text-xs font-semibold">{piece.type}</p>
                      <p className="text-[10px] opacity-70">{i === 0 ? "最上段" : `下から ${inspectStack.length - i} 段目`} • {piece.owner === "black" ? "黒" : "白"}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <button onClick={() => setInspectStack(null)} className="text-sm text-gray-400 hover:text-gray-700 text-center">閉じる</button>
          </div>
        </div>
      )}

      {loading && (
        <div className="fixed inset-0 bg-black/10 flex items-center justify-center pointer-events-none">
          <div className="bg-white px-4 py-2 rounded shadow text-sm text-gray-600">
            {gameState?.mode === "ai" && gameState.current_player === gameState.ai_player
              ? "AI 思考中..."
              : "処理中..."}
          </div>
        </div>
      )}
    </main>
    {homeBtn}{homeConfirmModal}
    </>
  );
}
