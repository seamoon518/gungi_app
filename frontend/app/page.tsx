"use client";

import { useState, useCallback } from "react";
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

// ── ルール選択情報 ──────────────────────────────────────────────────────────────
const LEVEL_INFO: {
  key: GameLevel;
  label: string;
  placement: string;
  special: string;
  tsuke: string;
  suiTsuke: string;
}[] = [
  { key: "nyumon",  label: "入門編", placement: "確定", special: "なし",    tsuke: "二段", suiTsuke: "なし" },
  { key: "shokyuu", label: "初級編", placement: "確定", special: "弓のみ",  tsuke: "二段", suiTsuke: "なし" },
  { key: "chukyuu", label: "中級編", placement: "自由", special: "あり",    tsuke: "二段", suiTsuke: "あり" },
  { key: "joukyuu", label: "上級編", placement: "自由", special: "あり",    tsuke: "三段", suiTsuke: "あり" },
];

function isSuiPlaced(state: GameState, player: Player): boolean {
  for (const row of state.board) {
    for (const cell of row) {
      if (cell.stack.some(p => p.type === "帥" && p.owner === player)) return true;
    }
  }
  return false;
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("title");
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [gameMode, setGameMode] = useState<GameMode>("pvp");
  const [aiDifficulty, setAiDifficulty] = useState<AiDifficulty>("easy");

  // Board selection state
  const [selectedCell, setSelectedCell] = useState<[number, number] | null>(null);
  const [highlights, setHighlights] = useState<[number, number][]>([]);
  const [enemyTsukeMoves, setEnemyTsukeMoves] = useState<[number, number][]>([]);
  const [pendingChoice, setPendingChoice] = useState<PendingChoice | null>(null);

  // Hand piece (arata / setup) state — reused for both play and setup phase
  const [selectedHandPiece, setSelectedHandPiece] = useState<PieceType | null>(null);
  const [arataHighlights, setArataHighlights] = useState<[number, number][]>([]);

  // 凝 mode (stack inspector)
  const [gizokuMode, setGizokuMode] = useState(false);
  const [inspectStack, setInspectStack] = useState<Piece[] | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const clearAll = () => {
    setSelectedCell(null);
    setHighlights([]);
    setEnemyTsukeMoves([]);
    setPendingChoice(null);
    setSelectedHandPiece(null);
    setArataHighlights([]);
    setGizokuMode(false);
    setInspectStack(null);
    setError(null);
  };

  // Start a game with selected level
  const handleSelectLevel = useCallback(async (level: GameLevel) => {
    setLoading(true);
    setError(null);
    try {
      const state = await api.newGame(
        level,
        gameMode,
        gameMode === "ai" ? aiDifficulty : undefined,
      );
      setGameState(state);
      clearAll();
      setScreen("game");
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameMode, aiDifficulty]);

  const handleResign = useCallback(async () => {
    if (!gameState) return;
    setLoading(true);
    try {
      const state = await api.resign(gameState.game_id);
      setGameState(state);
      clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState]);

  // Execute a board move (or tsuke)
  const executeMove = useCallback(async (
    fromRow: number, fromCol: number,
    toRow: number, toCol: number,
    action: MoveAction
  ) => {
    if (!gameState) return;
    setLoading(true);
    setPendingChoice(null);
    try {
      const state = await api.move(gameState.game_id, fromRow, fromCol, toRow, toCol, action);
      setGameState(state);
      clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState]);

  // Execute arata (place hand piece — play phase)
  const executeArata = useCallback(async (toRow: number, toCol: number) => {
    if (!gameState || !selectedHandPiece) return;
    setLoading(true);
    try {
      const state = await api.arata(gameState.game_id, selectedHandPiece, toRow, toCol);
      setGameState(state);
      clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState, selectedHandPiece]);

  // Execute setup placement (setup phase)
  const executeSetupPlace = useCallback(async (toRow: number, toCol: number) => {
    if (!gameState || !selectedHandPiece) return;
    setLoading(true);
    try {
      const state = await api.setupPlace(gameState.game_id, selectedHandPiece, toRow, toCol);
      setGameState(state);
      clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState, selectedHandPiece]);

  // Declare 済 (setup phase)
  const handleSetupDone = useCallback(async () => {
    if (!gameState || loading) return;
    setLoading(true);
    try {
      const state = await api.setupDone(gameState.game_id);
      setGameState(state);
      clearAll();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState, loading]);

  // Handle hand piece selection (works for both play and setup phase)
  const handleHandPieceClick = useCallback(async (type: PieceType) => {
    if (!gameState || loading) return;
    setError(null);

    // Toggle off if same piece clicked again
    if (selectedHandPiece === type) {
      setSelectedHandPiece(null);
      setArataHighlights([]);
      return;
    }

    // In setup phase: validate SUI must be first
    if (gameState.phase === "setup") {
      const suiOnBoard = isSuiPlaced(gameState, gameState.current_player);
      if (!suiOnBoard && type !== "帥") {
        setError("帥を先に配置してください。");
        return;
      }
    }

    // Clear board selection
    setSelectedCell(null);
    setHighlights([]);
    setEnemyTsukeMoves([]);

    setSelectedHandPiece(type);
    setLoading(true);
    try {
      if (gameState.phase === "setup") {
        const { valid_positions } = await api.getValidSetupPositions(gameState.game_id);
        setArataHighlights(valid_positions as [number, number][]);
      } else {
        const { valid_positions } = await api.getValidArata(gameState.game_id);
        setArataHighlights(valid_positions as [number, number][]);
      }
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [gameState, selectedHandPiece, loading]);

  // Handle cell click (board)
  const handleCellClick = useCallback(async (row: number, col: number) => {
    if (!gameState || gameState.game_over || loading) return;
    setError(null);

    // 凝 mode: show stack inspector
    if (gizokuMode) {
      const stack = gameState.board[row][col].stack;
      setInspectStack(stack.length > 0 ? stack : null);
      return;
    }

    // ── Setup phase ──────────────────────────────────────────────────────────
    if (gameState.phase === "setup") {
      if (selectedHandPiece) {
        const isValid = arataHighlights.some(([r, c]) => r === row && c === col);
        if (isValid) {
          await executeSetupPlace(row, col);
        } else {
          setSelectedHandPiece(null);
          setArataHighlights([]);
        }
      }
      return; // Cannot move board pieces during setup
    }

    // ── Play phase ───────────────────────────────────────────────────────────

    // Arata mode: clicking a valid arata position places the hand piece
    if (selectedHandPiece) {
      const isValid = arataHighlights.some(([r, c]) => r === row && c === col);
      if (isValid) {
        await executeArata(row, col);
      } else {
        setSelectedHandPiece(null);
        setArataHighlights([]);
      }
      return;
    }

    // Move mode: clicking a highlighted destination
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

    // Deselect if clicking same cell
    if (selectedCell && selectedCell[0] === row && selectedCell[1] === col) {
      setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]);
      return;
    }

    // Try to select an own piece
    const stack = gameState.board[row][col].stack;
    if (!stack.length) { setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]); return; }
    const top = stack[stack.length - 1];
    if (top.owner !== gameState.current_player) { setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]); return; }

    setLoading(true);
    try {
      const { valid_moves, enemy_tsuke_moves } = await api.getValidMoves(gameState.game_id, row, col);
      setSelectedCell([row, col]);
      setHighlights(valid_moves as [number, number][]);
      setEnemyTsukeMoves(enemy_tsuke_moves as [number, number][]);
      setSelectedHandPiece(null);
      setArataHighlights([]);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [
    gameState, selectedCell, highlights, enemyTsukeMoves,
    selectedHandPiece, arataHighlights,
    gizokuMode, loading,
    executeMove, executeArata, executeSetupPlace,
  ]);

  // ─── Rule select screen (shared by PvP and AI) ────────────────────────────
  const renderRuleSelect = (backScreen: Screen) => (
    <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-5 p-4">
      <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍議</h1>
      <p className="text-lg text-gray-600">どのルールで遊びますか？</p>
      <div className="flex flex-col gap-3 w-full max-w-md">
        {LEVEL_INFO.map(({ key, label, placement, special, tsuke, suiTsuke }) => (
          <button
            key={key}
            onClick={() => handleSelectLevel(key)}
            disabled={loading}
            className="flex flex-col items-stretch text-left rounded-xl overflow-hidden border-2 border-blue-400 hover:border-blue-600 hover:shadow-lg transition disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            {/* Header */}
            <div className="bg-blue-600 text-white px-4 py-2 font-bold text-base tracking-wide">
              {label}
            </div>
            {/* Details box */}
            <div className="bg-white px-4 py-3 border-t-0">
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-gray-700">
                <div className="flex gap-1">
                  <span className="text-gray-400 shrink-0">初期配置：</span>
                  <span className="font-medium">{placement}</span>
                </div>
                <div className="flex gap-1">
                  <span className="text-gray-400 shrink-0">特殊駒：</span>
                  <span className="font-medium">{special}</span>
                </div>
                <div className="flex gap-1">
                  <span className="text-gray-400 shrink-0">ツケ：</span>
                  <span className="font-medium">{tsuke}</span>
                </div>
                <div className="flex gap-1">
                  <span className="text-gray-400 shrink-0">師ツケ：</span>
                  <span className="font-medium">{suiTsuke}</span>
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>
      <button
        onClick={() => setScreen(backScreen)}
        className="text-sm text-gray-400 hover:text-gray-600 underline mt-1"
      >
        ← 戻る
      </button>
      {error && <p className="text-red-500 text-sm">{error}</p>}
    </main>
  );

  // ─── Screens ───────────────────────────────────────────────────────────────

  if (screen === "title") {
    return (
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8">
        <h1 className="text-5xl font-bold tracking-widest text-gray-800">軍議</h1>
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
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8">
        <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍議</h1>
        <p className="text-lg text-gray-600">対戦モードを選択してください</p>
        <div className="flex flex-col gap-4 w-72">
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
            <span className="text-xs text-gray-500 mt-1">コンピューターと対戦します</span>
          </button>
        </div>
        <button onClick={() => setScreen("title")} className="text-sm text-gray-400 hover:text-gray-600 underline">
          ← タイトルに戻る
        </button>
      </main>
    );
  }

  if (screen === "pvp_rule_select") {
    return renderRuleSelect("mode_select");
  }

  if (screen === "ai_difficulty_select") {
    return (
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8">
        <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍議</h1>
        <p className="text-lg text-gray-600">誰と対戦しますか？</p>
        <div className="flex flex-col gap-4 w-72">
          {(["easy", "normal", "hard"] as AiDifficulty[]).map((diff) => {
            const label = diff === "easy" ? "簡単" : diff === "normal" ? "普通" : "難しい";
            return (
              <button
                key={diff}
                onClick={() => { setAiDifficulty(diff); setScreen("ai_rule_select"); }}
                className="px-6 py-4 bg-white border-2 border-amber-500 rounded-xl hover:bg-amber-50 transition shadow font-bold text-amber-700 text-lg"
              >
                {label}
              </button>
            );
          })}
        </div>
        <button onClick={() => setScreen("mode_select")} className="text-sm text-gray-400 hover:text-gray-600 underline">
          ← 戻る
        </button>
      </main>
    );
  }

  if (screen === "ai_rule_select") {
    return renderRuleSelect("ai_difficulty_select");
  }

  // ─── Game screen ───────────────────────────────────────────────────────────
  return (
    <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center p-4 gap-4">
      <h1 className="text-2xl font-bold tracking-widest text-gray-800">軍議</h1>

      {gameState && (
        <div className="flex flex-row gap-6 items-start">

          {/* Left: setup banner + board */}
          <div className="flex flex-col gap-3">
            {gameState.phase === "setup" && (
              <div className="bg-yellow-50 border-2 border-yellow-400 rounded-xl p-3 text-sm max-w-[504px]">
                <p className="font-bold text-yellow-800 text-base mb-1">初期配置フェーズ</p>
                <p className="text-yellow-700 mb-2">
                  {!isSuiPlaced(gameState, gameState.current_player)
                    ? "まず帥（スイ）を自陣に配置してください"
                    : "駒を選んで自陣（3列目まで）に配置してください"}
                </p>
                <div className="flex gap-4 text-xs font-medium">
                  <span className={`px-2 py-0.5 rounded-full border ${
                    gameState.setup_done.black
                      ? "bg-green-100 border-green-400 text-green-700"
                      : "bg-gray-100 border-gray-300 text-gray-500"
                  }`}>
                    黒: {gameState.setup_done.black ? "済 ✓" : "配置中..."}
                  </span>
                  <span className={`px-2 py-0.5 rounded-full border ${
                    gameState.setup_done.white
                      ? "bg-green-100 border-green-400 text-green-700"
                      : "bg-gray-100 border-gray-300 text-gray-500"
                  }`}>
                    白: {gameState.setup_done.white ? "済 ✓" : "配置中..."}
                  </span>
                </div>
              </div>
            )}

            <Board
              state={gameState}
              selectedCell={selectedCell}
              highlights={highlights}
              enemyTsukeMoves={enemyTsukeMoves}
              arataHighlights={arataHighlights}
              gizokuMode={gizokuMode}
              onCellClick={handleCellClick}
            />
          </div>

          {/* Right: game info + 済ボタン */}
          <div className="flex flex-col gap-3">
            <GameInfo
              state={gameState}
              selectedHandPiece={selectedHandPiece}
              gizokuMode={gizokuMode}
              onHandPieceClick={handleHandPieceClick}
              onGizokuToggle={() => {
                setGizokuMode(v => !v);
                setSelectedCell(null);
                setHighlights([]);
                setEnemyTsukeMoves([]);
                setSelectedHandPiece(null);
                setArataHighlights([]);
                setInspectStack(null);
              }}
              onNewGame={() => setScreen("mode_select")}
              onResign={handleResign}
              error={error}
            />

            {/* 済を宣言ボタン（setup phase のみ） */}
            {gameState.phase === "setup" && !gameState.game_over && (
              <button
                onClick={handleSetupDone}
                disabled={!isSuiPlaced(gameState, gameState.current_player) || loading}
                className="px-4 py-3 bg-green-600 text-white font-bold rounded-xl hover:bg-green-700 transition disabled:opacity-40 disabled:cursor-not-allowed text-sm shadow"
              >
                済を宣言する
              </button>
            )}
          </div>
        </div>
      )}

      {/* 取る or ツケる choice */}
      {pendingChoice && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl p-6 w-72 flex flex-col gap-4">
            <p className="text-center font-bold text-gray-800">どうしますか？</p>
            <p className="text-center text-sm text-gray-500">相手の駒の上に移動します</p>
            <button
              onClick={() => executeMove(pendingChoice.fromRow, pendingChoice.fromCol, pendingChoice.toRow, pendingChoice.toCol, "capture")}
              className="py-3 bg-red-600 text-white font-bold rounded-lg hover:bg-red-700 transition"
            >取る（敵駒を除去）</button>
            <button
              onClick={() => executeMove(pendingChoice.fromRow, pendingChoice.fromCol, pendingChoice.toRow, pendingChoice.toCol, "tsuke_enemy")}
              className="py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 transition"
            >ツケる（重ねる）</button>
            <button onClick={() => setPendingChoice(null)} className="py-2 text-gray-500 text-sm hover:text-gray-800">キャンセル</button>
          </div>
        </div>
      )}

      {/* 凝 stack inspector modal */}
      {gizokuMode && inspectStack !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setInspectStack(null)}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-64 flex flex-col gap-3" onClick={e => e.stopPropagation()}>
            <p className="text-center font-bold text-gray-800">凝 — スタック確認</p>
            {inspectStack.length === 0 ? (
              <p className="text-center text-gray-400 text-sm">このマスは空です</p>
            ) : (
              <div className="flex flex-col gap-2">
                {[...inspectStack].reverse().map((piece, i) => (
                  <div key={i} className={`
                    flex items-center gap-3 px-3 py-2 rounded-lg border
                    ${piece.owner === "black" ? "bg-gray-900 text-white border-gray-700" : "bg-white text-gray-900 border-gray-300"}
                  `}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border
                      ${piece.owner === "black" ? "bg-gray-800 text-white border-gray-600" : "bg-gray-50 text-gray-900 border-gray-400"}
                    `}>
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
          <div className="bg-white px-4 py-2 rounded shadow text-sm text-gray-600">処理中...</div>
        </div>
      )}
    </main>
  );
}
