"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  GameState, MoveAction, Piece, PieceType,
  Player, GameLevel, GameMode, AiDifficulty,
} from "@/types/game";
import { api, ApiError, errorMessage } from "@/lib/api";
import Board from "@/components/Board";
import GameInfo from "@/components/GameInfo";

type Screen =
  | "title"
  | "mode_select"
  | "pvp_rule_select"
  | "ai_difficulty_select"
  | "ai_player_select"     // AI vs Human: 先手/後手/ランダム選択
  | "ai_rule_select"
  | "ai_vs_ai_setup"       // AI同士: 両側の強さを選ぶ画面
  | "ai_vs_ai_rule_select" // AI同士: ルール選択
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

const DIFF_LABEL: Record<AiDifficulty, string> = { easy: "簡単", normal: "普通", hard: "難しい" };

function isSuiPlaced(state: GameState, player: Player): boolean {
  for (const row of state.board)
    for (const cell of row)
      if (cell.stack.some(p => p.type === "帥" && p.owner === player)) return true;
  return false;
}

/** いま AI が指す番か（AI同士は常に AI、AI対戦は AI 側の手番のみ） */
function isAiTurn(state: GameState): boolean {
  if (state.game_over) return false;
  if (state.mode === "ai_vs_ai") return true;
  return state.mode === "ai" && !!state.ai_player && state.current_player === state.ai_player;
}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * AI に 1 手指させる。通信エラーは 2 回まで自動で再試行する。
 * 400（サーバー側ではすでに手番が進んでいる等）のときは最新状態を取り直して続行する。
 */
async function requestAiMove(prev: GameState, isCancelled: () => boolean): Promise<GameState> {
  const waits = [1000, 2000];
  for (let attempt = 0; ; attempt++) {
    try {
      return await api.aiMove(prev.game_id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        const fresh = await api.getState(prev.game_id);
        const progressed =
          fresh.game_over || !isAiTurn(fresh) ||
          fresh.current_player !== prev.current_player || fresh.phase !== prev.phase ||
          JSON.stringify(fresh.board) !== JSON.stringify(prev.board);
        if (progressed) return fresh;
        throw e;
      }
      if (e instanceof ApiError && e.status === 404) throw e;
      if (attempt >= waits.length || isCancelled()) throw e;
      await sleep(waits[attempt]);
      if (isCancelled()) throw e;
    }
  }
}

// 再読み込み・アプリ切替後に対局へ復帰するため、対局IDをブラウザに保存する
const SAVED_GAME_KEY = "gungi:lastGameId";
function saveGameId(id: string | null) {
  try {
    if (id) localStorage.setItem(SAVED_GAME_KEY, id);
    else localStorage.removeItem(SAVED_GAME_KEY);
  } catch { /* プライベートモード等で使えない場合は保存しない */ }
}
function loadGameId(): string | null {
  try { return localStorage.getItem(SAVED_GAME_KEY); } catch { return null; }
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("title");
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [gameMode, setGameMode] = useState<GameMode>("pvp");
  const [aiDifficulty, setAiDifficulty] = useState<AiDifficulty>("easy");
  // AI同士モード用
  const [aiDifficultyBlack, setAiDifficultyBlack] = useState<AiDifficulty>("easy");
  const [aiDifficultyWhite, setAiDifficultyWhite] = useState<AiDifficulty>("easy");
  // AI vs Human: 人間が担当する陣（"black"=先手, "white"=後手, "random"=ランダム）
  const [humanPlayer, setHumanPlayer] = useState<Player | "random">("black");

  const [selectedCell, setSelectedCell] = useState<[number, number] | null>(null);
  const [highlights, setHighlights] = useState<[number, number][]>([]);
  const [enemyTsukeMoves, setEnemyTsukeMoves] = useState<[number, number][]>([]);
  // 相手駒の移動範囲プレビュー
  const [enemyPreviewCell, setEnemyPreviewCell] = useState<[number, number] | null>(null);
  const [enemyPreviewMoves, setEnemyPreviewMoves] = useState<[number, number][]>([]);
  const [pendingChoice, setPendingChoice] = useState<PendingChoice | null>(null);

  const [selectedHandPiece, setSelectedHandPiece] = useState<PieceType | null>(null);
  const [arataHighlights, setArataHighlights] = useState<[number, number][]>([]);

  const [gizokuMode, setGizokuMode] = useState(false);
  // スタック確認中のマス（盤面が更新されても最新のスタックを表示する）
  const [inspectCell, setInspectCell] = useState<[number, number] | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showHomeConfirm, setShowHomeConfirm] = useState(false);
  // 謀の寝返り：対象選択モーダル用
  const [boushouTargets, setBoushouTargets] = useState<{ index: number; piece: Piece }[] | null>(null);
  // AI の思考中フラグと、自動再試行でも回復しなかったエラー（再試行ボタンで再開）
  const [aiThinking, setAiThinking] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  // タイトル画面に出すお知らせ（対局の復帰に失敗した場合など）
  const [notice, setNotice] = useState<string | null>(null);

  // 表示中の対局ID。ホームに戻った後や別の対局に切り替えた後に届いた古い応答で画面を上書きしないために使う
  const activeGameIdRef = useRef<string | null>(null);
  // 送信中の操作があるか（素早い連続タップで同じ操作が二重送信されるのを防ぐ）
  const busyRef = useRef(false);

  // 選択・ハイライトだけを解除する（AI が指した後も凝モードやスタック確認は維持する）
  const clearSelection = () => {
    setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]);
    setPendingChoice(null); setSelectedHandPiece(null); setArataHighlights([]);
    setBoushouTargets(null);
    setEnemyPreviewCell(null); setEnemyPreviewMoves([]);
  };

  const clearAll = () => {
    clearSelection();
    setGizokuMode(false); setInspectCell(null); setError(null);
  };

  /** 表示中の対局の応答だけを反映する（古い対局の応答は捨てる） */
  const applyState = (state: GameState): boolean => {
    if (activeGameIdRef.current !== state.game_id) return false;
    setGameState(state);
    return true;
  };

  /** 対局画面を開く（新規・復帰共通） */
  const openGame = (state: GameState) => {
    activeGameIdRef.current = state.game_id;
    saveGameId(state.game_id);
    setGameState(state); clearAll(); setAiError(null); setAiThinking(false); setNotice(null);
    setScreen("game");
  };

  /** 対局を閉じてタイトルへ */
  const closeGame = () => {
    activeGameIdRef.current = null;
    saveGameId(null);
    setScreen("title"); setGameState(null); clearAll(); setAiError(null); setAiThinking(false);
  };

  // 起動時: 前回の対局が残っていれば復帰する（再読み込み・スマホのアプリ切替対策）
  useEffect(() => {
    const savedId = loadGameId();
    if (!savedId) return;
    let cancelled = false;
    api.getState(savedId)
      .then(state => { if (!cancelled && activeGameIdRef.current === null) openGame(state); })
      .catch(e => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          saveGameId(null);
          setNotice("前回の対局データが見つかりませんでした（サーバーが再起動された可能性があります）。新しい対局を始めてください。");
        } else {
          setNotice(`前回の対局を読み込めませんでした: ${errorMessage(e)}`);
        }
      });
    return () => { cancelled = true; };
    // 起動時に一度だけ実行する
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // AI の手番を自動トリガー（AI vs Human / AI vs AI 共通）
  const aiTriggeringRef = useRef(false);
  useEffect(() => {
    if (screen !== "game") return;
    if (!gameState) return;
    if (gameState.game_over) return;
    if (gameState.mode !== "ai" && gameState.mode !== "ai_vs_ai") return;
    if (!gameState.ai_player) return;
    if (aiError) return; // 再試行ボタンが押されるまで止める

    // AI vs Human: 手番が AI のときだけ動く
    // AI vs AI: 常に動く（ai_player === "both"）
    if (!isAiTurn(gameState)) return;
    if (aiTriggeringRef.current) return;

    aiTriggeringRef.current = true;
    // ホームに戻る・別の対局を始める等でこの effect が破棄されたら、以降の応答は画面に反映しない
    let cancelled = false;
    const gameId = gameState.game_id;
    const isStale = () => cancelled || activeGameIdRef.current !== gameId;
    // AI vs AI は視覚的なテンポを確保するため少し長めに待つ
    const delay = gameState.mode === "ai_vs_ai" ? 600 : 400;

    const timer = setTimeout(async () => {
      setAiThinking(true);
      try {
        if (gameState.mode === "ai_vs_ai") {
          // AI同士: 1手指して依存配列の変化で再トリガー。
          // ただし setup フェーズで同じプレイヤーが連続して指す場合はループで続ける。
          let currentState = gameState;
          const startPlayer = currentState.current_player;
          do {
            const state = await requestAiMove(currentState, isStale);
            if (isStale()) return;
            setGameState(state);
            clearSelection();
            currentState = state;
          } while (
            !currentState.game_over &&
            currentState.phase === "setup" &&
            currentState.current_player === startPlayer
          );
        } else {
          // AI vs Human: セットアップで連続手番が続く場合はループで処理
          let currentState = gameState;
          while (isAiTurn(currentState)) {
            const state = await requestAiMove(currentState, isStale);
            if (isStale()) return;
            setGameState(state);
            clearSelection();
            currentState = state;
          }
        }
      } catch (e) {
        if (!isStale()) setAiError(errorMessage(e));
      } finally {
        setAiThinking(false);
        if (!cancelled) aiTriggeringRef.current = false;
      }
    }, delay);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      aiTriggeringRef.current = false;
    };
    // 手番・対局・終局・エラー状態が変わったときだけ再評価する（盤面の更新ごとには再起動しない）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen, gameState?.game_id, gameState?.current_player, gameState?.game_over, gameState?.phase, aiError]);

  /**
   * ユーザー操作を 1 つずつ実行する。送信中は次の操作を受け付けない（二重送信防止）。
   * 応答が届いた時点で別の対局に切り替わっていれば反映しない。
   */
  const runAction = useCallback(async (call: () => Promise<GameState>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    try {
      const state = await call();
      if (applyState(state)) clearAll();
    } catch (e) { setError(errorMessage(e)); }
    finally { busyRef.current = false; setLoading(false); }
    // applyState / clearAll は state setter と ref だけを使うため再生成不要
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelectLevel = useCallback(async (level: GameLevel) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLoading(true); setError(null);
    try {
      // "random" の場合はここで解決する
      const resolvedHumanPlayer: Player | undefined =
        gameMode === "ai"
          ? humanPlayer === "random"
            ? (Math.random() < 0.5 ? "black" : "white")
            : humanPlayer
          : undefined;

      const state = await api.newGame(
        level,
        gameMode,
        gameMode === "ai" ? aiDifficulty : undefined,
        gameMode === "ai_vs_ai" ? aiDifficultyBlack : undefined,
        gameMode === "ai_vs_ai" ? aiDifficultyWhite : undefined,
        resolvedHumanPlayer,
      );
      openGame(state);
    } catch (e) { setError(errorMessage(e)); }
    finally { busyRef.current = false; setLoading(false); }
    // openGame は state setter と ref だけを使うため依存に含めない
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameMode, aiDifficulty, aiDifficultyBlack, aiDifficultyWhite, humanPlayer]);

  const handleResign = useCallback(async () => {
    if (!gameState || isAiTurn(gameState)) return;
    await runAction(() => api.resign(gameState.game_id));
  }, [gameState, runAction]);

  const executeMove = useCallback(async (
    fromRow: number, fromCol: number, toRow: number, toCol: number, action: MoveAction
  ) => {
    if (!gameState) return;
    setPendingChoice(null);
    await runAction(() => api.move(gameState.game_id, fromRow, fromCol, toRow, toCol, action));
  }, [gameState, runAction]);

  const executeArata = useCallback(async (toRow: number, toCol: number) => {
    if (!gameState || !selectedHandPiece) return;
    await runAction(() => api.arata(gameState.game_id, selectedHandPiece, toRow, toCol));
  }, [gameState, selectedHandPiece, runAction]);

  const executeSetupPlace = useCallback(async (toRow: number, toCol: number) => {
    if (!gameState || !selectedHandPiece) return;
    await runAction(() => api.setupPlace(gameState.game_id, selectedHandPiece, toRow, toCol));
  }, [gameState, selectedHandPiece, runAction]);

  const executeBoushou = useCallback(async (targetIndex: number) => {
    if (!gameState || !pendingChoice) return;
    setBoushouTargets(null);
    setPendingChoice(null);
    await runAction(() => api.boushou(
      gameState.game_id,
      pendingChoice.fromRow, pendingChoice.fromCol,
      pendingChoice.toRow, pendingChoice.toCol,
      targetIndex,
    ));
  }, [gameState, pendingChoice, runAction]);

  // 長押しでスタック確認（凝モード不要・モバイル向け）
  const handleCellLongPress = useCallback((row: number, col: number) => {
    if (!gameState) return;
    setInspectCell(gameState.board[row][col].stack.length > 0 ? [row, col] : null);
  }, [gameState]);

  const handleSetupDone = useCallback(async () => {
    if (!gameState || isAiTurn(gameState)) return;
    await runAction(() => api.setupDone(gameState.game_id));
  }, [gameState, runAction]);

  const handleUndo = useCallback(async () => {
    if (!gameState || isAiTurn(gameState)) return;
    await runAction(() => api.undo(gameState.game_id));
  }, [gameState, runAction]);

  const handleHandPieceClick = useCallback(async (type: PieceType) => {
    if (!gameState || busyRef.current) return;
    if (gameState.mode === "ai_vs_ai") return; // 観戦モードは操作不可
    if (isAiTurn(gameState)) return;           // AI の手番中は操作不可
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
    busyRef.current = true;
    setLoading(true);
    try {
      const endpoint = gameState.phase === "setup"
        ? api.getValidSetupPositions(gameState.game_id)
        : api.getValidArata(gameState.game_id);
      const { valid_positions } = await endpoint;
      setArataHighlights(valid_positions as [number, number][]);
    } catch (e) { setError(errorMessage(e)); }
    finally { busyRef.current = false; setLoading(false); }
  }, [gameState, selectedHandPiece]);

  const handleCellClick = useCallback(async (row: number, col: number) => {
    if (!gameState || busyRef.current) return;

    // 凝モード: 観戦中・相手の手番・終局後でもスタックを確認できる
    if (gizokuMode) {
      setInspectCell(gameState.board[row][col].stack.length > 0 ? [row, col] : null);
      return;
    }

    if (gameState.game_over) return;
    if (gameState.mode === "ai_vs_ai") return; // 観戦モードはクリック無効
    if (isAiTurn(gameState)) return;           // AI の手番中は人間が駒を動かせない
    setError(null);

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
    if (!stack.length) {
      setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]);
      setEnemyPreviewCell(null); setEnemyPreviewMoves([]);
      return;
    }
    const topPiece = stack[stack.length - 1];

    if (topPiece.owner !== gameState.current_player) {
      // ── 相手駒タップ → 移動範囲プレビュー ────────────────────────────────
      if (enemyPreviewCell?.[0] === row && enemyPreviewCell?.[1] === col) {
        // 同じセルを再タップ → プレビュー解除
        setEnemyPreviewCell(null); setEnemyPreviewMoves([]);
      } else {
        setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]);
        setSelectedHandPiece(null); setArataHighlights([]);
        busyRef.current = true;
        setLoading(true);
        try {
          const { valid_moves } = await api.getValidMoves(gameState.game_id, row, col);
          setEnemyPreviewCell([row, col]);
          setEnemyPreviewMoves(valid_moves as [number, number][]);
        } catch (e) { setError(errorMessage(e)); }
        finally { busyRef.current = false; setLoading(false); }
      }
      return;
    }

    // ── 自駒タップ → 合法手表示（プレビューをクリア） ────────────────────
    busyRef.current = true;
    setLoading(true);
    try {
      const { valid_moves, enemy_tsuke_moves } = await api.getValidMoves(gameState.game_id, row, col);
      setSelectedCell([row, col]);
      setHighlights(valid_moves as [number, number][]);
      setEnemyTsukeMoves(enemy_tsuke_moves as [number, number][]);
      setSelectedHandPiece(null); setArataHighlights([]);
      setEnemyPreviewCell(null); setEnemyPreviewMoves([]);
    } catch (e) { setError(errorMessage(e)); }
    finally { busyRef.current = false; setLoading(false); }
  }, [
    gameState, selectedCell, highlights, enemyTsukeMoves,
    selectedHandPiece, arataHighlights, gizokuMode, enemyPreviewCell,
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

  // 人間が後手（白）のとき盤を 180° 反転する
  // ai_player === "black" = AI が先手 = 人間が後手
  const boardFlipped = gameState?.mode === "ai" && gameState?.ai_player === "black";

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
            onClick={() => { setShowHomeConfirm(false); closeGame(); }}
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
    <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-5 p-4 overflow-x-hidden w-full">
      <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍儀</h1>
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
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8 p-4 w-full">
        <h1 className="text-4xl sm:text-5xl font-bold tracking-widest text-gray-800">軍儀 <span className="text-lg font-normal text-gray-400">ver 5</span></h1>
        <p className="text-gray-500 text-sm">HUNTER×HUNTER の思考型ボードゲーム</p>
        <button
          onClick={() => { setNotice(null); setScreen("mode_select"); }}
          className="px-10 py-4 bg-blue-600 text-white text-xl rounded-xl hover:bg-blue-700 transition shadow-lg"
        >
          ゲームを始める
        </button>
        {notice && <p className="max-w-sm text-center text-sm text-red-500">{notice}</p>}
      </main>
    );
  }

  if (screen === "mode_select") {
    return (
      <>
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8 p-4 overflow-x-hidden w-full">
        <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍儀</h1>
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
          <button
            onClick={() => { setGameMode("ai_vs_ai"); setScreen("ai_vs_ai_setup"); }}
            className="flex flex-col items-start px-6 py-5 bg-white border-2 border-purple-500 rounded-xl hover:bg-purple-50 transition shadow"
          >
            <span className="text-lg font-bold text-purple-700">AI同士対戦（観戦）</span>
            <span className="text-xs text-gray-500 mt-1">AI同士の対局を観戦します</span>
          </button>
        </div>
      </main>
      {homeBtn}{homeConfirmModal}
    </>
    );
  }

  if (screen === "pvp_rule_select") return renderRuleSelect("mode_select");

  // ── AI同士: 強さ設定画面 ────────────────────────────────────────────────────
  if (screen === "ai_vs_ai_setup") {
    const DIFF_OPTIONS: { key: AiDifficulty; label: string; desc: string }[] = [
      { key: "easy",   label: "簡単",   desc: "弱め" },
      { key: "normal", label: "普通",   desc: "中程度" },
      { key: "hard",   label: "難しい", desc: "強め" },
    ];
    return (
      <>
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-6 p-4 overflow-x-hidden w-full">
        <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍儀</h1>
        <p className="text-lg text-gray-600">AI同士の強さを設定してください</p>

        <div className="flex flex-col sm:flex-row gap-6 w-full max-w-lg">
          {/* 黒陣（先手） */}
          <div className="flex-1 bg-white rounded-xl border-2 border-gray-300 p-4 flex flex-col gap-3">
            <p className="text-center font-bold text-gray-800">黒陣（先手）</p>
            {DIFF_OPTIONS.map(({ key, label, desc }) => (
              <button
                key={key}
                onClick={() => setAiDifficultyBlack(key)}
                className={`w-full py-2.5 rounded-lg text-sm font-bold border-2 transition ${
                  aiDifficultyBlack === key
                    ? "bg-gray-900 text-white border-gray-900"
                    : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                }`}
              >
                {label}
                <span className="ml-1 text-xs font-normal opacity-60">（{desc}）</span>
              </button>
            ))}
          </div>

          {/* 白陣（後手） */}
          <div className="flex-1 bg-white rounded-xl border-2 border-gray-300 p-4 flex flex-col gap-3">
            <p className="text-center font-bold text-gray-800">白陣（後手）</p>
            {DIFF_OPTIONS.map(({ key, label, desc }) => (
              <button
                key={key}
                onClick={() => setAiDifficultyWhite(key)}
                className={`w-full py-2.5 rounded-lg text-sm font-bold border-2 transition ${
                  aiDifficultyWhite === key
                    ? "bg-white text-gray-900 border-gray-900 shadow"
                    : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                }`}
              >
                {label}
                <span className="ml-1 text-xs font-normal opacity-60">（{desc}）</span>
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={() => setScreen("ai_vs_ai_rule_select")}
          className="px-10 py-3 bg-purple-600 text-white text-base font-bold rounded-xl hover:bg-purple-700 transition shadow-lg"
        >
          次へ → ルール選択
        </button>
        <button onClick={() => setScreen("mode_select")} className="text-sm text-gray-400 hover:text-gray-600 underline">← 戻る</button>
      </main>
      {homeBtn}{homeConfirmModal}
      </>
    );
  }

  if (screen === "ai_vs_ai_rule_select") return renderRuleSelect("ai_vs_ai_setup");

  if (screen === "ai_difficulty_select") {
    return (
      <>
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-8 p-4 overflow-x-hidden w-full">
        <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍儀</h1>
        <p className="text-lg text-gray-600">誰と対戦しますか？</p>
        <div className="flex flex-col gap-4 w-full max-w-xs">
          {(["easy", "normal", "hard"] as AiDifficulty[]).map((diff) => {
            const label = diff === "easy" ? "簡単" : diff === "normal" ? "普通" : "難しい";
            return (
              <button key={diff} onClick={() => { setAiDifficulty(diff); setScreen("ai_player_select"); }}
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

  // ── AI vs Human: 先手/後手/ランダム 選択画面 ──────────────────────────────────
  if (screen === "ai_player_select") {
    const OPTIONS: { value: Player | "random"; label: string; sub: string; bg: string; border: string; text: string }[] = [
      {
        value: "black",
        label: "先手（黒陣）",
        sub: "あなたが最初に動きます",
        bg: "bg-gray-900", border: "border-gray-900", text: "text-white",
      },
      {
        value: "white",
        label: "後手（白陣）",
        sub: "AIが先に動きます",
        bg: "bg-white", border: "border-gray-400", text: "text-gray-900",
      },
      {
        value: "random",
        label: "ランダム",
        sub: "先手・後手をランダムで決定",
        bg: "bg-gradient-to-r from-gray-900 to-white", border: "border-amber-400", text: "text-amber-700",
      },
    ];
    return (
      <>
      <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center gap-6 p-4 overflow-x-hidden w-full">
        <h1 className="text-3xl font-bold tracking-widest text-gray-800">軍儀</h1>
        <p className="text-lg text-gray-600">先手・後手を選んでください</p>
        <div className="flex flex-col gap-4 w-full max-w-xs">
          {OPTIONS.map(({ value, label, sub, bg, border, text }) => (
            <button
              key={value}
              onClick={() => { setHumanPlayer(value); setScreen("ai_rule_select"); }}
              className={`
                flex flex-col items-start px-6 py-5 rounded-xl border-2 shadow transition
                hover:brightness-95
                ${humanPlayer === value ? "ring-4 ring-blue-400 scale-[1.02]" : ""}
                ${bg} ${border}
              `}
            >
              <span className={`text-lg font-bold ${text}`}>{label}</span>
              <span className="text-xs text-gray-400 mt-1">{sub}</span>
            </button>
          ))}
        </div>
        <button onClick={() => setScreen("ai_difficulty_select")} className="text-sm text-gray-400 hover:text-gray-600 underline">← 戻る</button>
      </main>
      {homeBtn}{homeConfirmModal}
      </>
    );
  }

  if (screen === "ai_rule_select") return renderRuleSelect("ai_player_select");

  // ─── ゲーム画面 ─────────────────────────────────────────────────────
  const inspectStack: Piece[] | null =
    inspectCell && gameState ? gameState.board[inspectCell[0]][inspectCell[1]].stack : null;

  // 謀の寝返り発動条件チェック: 動かす駒が謀で、ツケ先に手駒と同種の敵駒があるとき
  const pendingBoushouTargets: { index: number; piece: Piece }[] = (() => {
    if (!pendingChoice || !gameState) return [];
    const srcStack = gameState.board[pendingChoice.fromRow][pendingChoice.fromCol]?.stack ?? [];
    if (srcStack[srcStack.length - 1]?.type !== "謀") return [];
    const destStack = gameState.board[pendingChoice.toRow][pendingChoice.toCol]?.stack ?? [];
    const enemyPlayer = gameState.current_player === "black" ? "white" : "black";
    const handTypes = new Set((gameState.hand_pieces[gameState.current_player] ?? []).map(p => p.type));
    return destStack
      .map((piece, index) => ({ index, piece }))
      .filter(({ piece }) => piece.owner === enemyPlayer && handTypes.has(piece.type));
  })();

  return (
    <>
    <main className="min-h-screen bg-amber-50 flex flex-col items-center justify-center p-2 sm:p-4 gap-3 overflow-x-hidden w-full">
      <h1 className="text-xl sm:text-2xl font-bold tracking-widest text-gray-800">軍儀</h1>

      {gameState && (
        <>
          {/* ゲームオーバー表示 */}
          {gameState.game_over && (
            <div className="text-center bg-white rounded-xl shadow px-6 py-3">
              <p className="text-lg font-bold text-red-600">ゲーム終了</p>
              {gameState.winner
                ? <p className="text-sm mt-1"><span className="font-semibold">{gameState.winner === "black" ? "黒陣" : "白陣"}</span> の勝利！</p>
                : <p className="text-sm mt-1">
                    {gameState.end_reason === "move_limit"
                      ? `手数上限（${gameState.move_count}手）に達したため引き分け`
                      : "千日手（引き分け）"}
                  </p>
              }
            </div>
          )}

          {/* AI同士: 観戦バナー */}
          {gameState.mode === "ai_vs_ai" && !gameState.game_over && (
            <div className="bg-purple-50 border-2 border-purple-300 rounded-xl px-4 py-2 text-sm text-purple-700 font-medium text-center w-full">
              🤖 AI同士対戦 観戦中
              <span className="ml-3 text-xs text-purple-500 font-normal">
                黒: {gameState.ai_difficulty_black ? DIFF_LABEL[gameState.ai_difficulty_black] : "?"}　白: {gameState.ai_difficulty_white ? DIFF_LABEL[gameState.ai_difficulty_white] : "?"}
              </span>
            </div>
          )}

          {/* AI の通信エラー（自動再試行でも回復しなかった場合） */}
          {aiError && !gameState.game_over && (
            <div className="bg-red-50 border-2 border-red-300 rounded-xl px-4 py-2 text-sm text-red-700 w-full flex flex-col sm:flex-row items-center justify-between gap-2">
              <span className="text-center sm:text-left">AI の手を取得できませんでした: {aiError}</span>
              <button
                onClick={() => setAiError(null)}
                className="shrink-0 px-4 py-1.5 bg-red-600 text-white font-bold rounded-lg hover:bg-red-700 transition"
              >
                再試行
              </button>
            </div>
          )}

          {/* setup フェーズバナー */}
          {gameState.phase === "setup" && (
            <div className="bg-yellow-50 border-2 border-yellow-400 rounded-xl p-3 text-sm w-full">
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
            レイアウト（boardFlipped = 人間が後手のとき）:
            ・通常（先手/PvP）: 白パネル → ボード → 黒パネル
            ・反転（後手）:     黒パネル → ボード(反転) → 白パネル
              mobile 縦: 相手パネル(上) → ボード → 自分パネル(下)
              PC 横:     相手パネル(左) | ボード(反転) | 自分パネル(右)
          */}
          {(() => {
            const gizokuReset = () => { setGizokuMode(v => !v); setSelectedCell(null); setHighlights([]); setEnemyTsukeMoves([]); setSelectedHandPiece(null); setArataHighlights([]); setInspectCell(null); };

            const whitePanel = (
              <GameInfo
                state={gameState}
                player="white"
                flipped={!boardFlipped}  // PvP/先手時は lg:rotate-180、後手時は不要
                selectedHandPiece={gameState.current_player === "white" ? selectedHandPiece : null}
                gizokuMode={gizokuMode}
                onHandPieceClick={handleHandPieceClick}
                onGizokuToggle={gizokuReset}
                onResign={handleResign}
                onSetupDone={handleSetupDone}
                onUndo={handleUndo}
                error={gameState.current_player === "white" ? error : null}
              />
            );

            const blackPanel = (
              <GameInfo
                state={gameState}
                player="black"
                flipped={false}
                selectedHandPiece={gameState.current_player === "black" ? selectedHandPiece : null}
                gizokuMode={gizokuMode}
                onHandPieceClick={handleHandPieceClick}
                onGizokuToggle={gizokuReset}
                onResign={handleResign}
                onSetupDone={handleSetupDone}
                onUndo={handleUndo}
                error={gameState.current_player === "black" ? error : null}
              />
            );

            const boardEl = (
              <div className="flex justify-center items-start w-full lg:w-auto">
                <Board
                  state={gameState}
                  selectedCell={selectedCell}
                  highlights={highlights}
                  enemyTsukeMoves={enemyTsukeMoves}
                  arataHighlights={arataHighlights}
                  lastMoveHighlights={lastMoveHighlights}
                  gizokuMode={gizokuMode}
                  onCellClick={handleCellClick}
                  onCellLongPress={handleCellLongPress}
                  enemyPreviewCell={enemyPreviewCell}
                  enemyPreviewMoves={enemyPreviewMoves}
                  flipped={boardFlipped}
                />
              </div>
            );

            return (
              <div className="flex flex-col lg:flex-row items-stretch lg:items-start lg:justify-center gap-3 w-full max-w-screen-xl">
                {boardFlipped ? (
                  // 後手（白）視点: 相手(黒)パネルが上/左、自分(白)パネルが下/右
                  <>{blackPanel}{boardEl}{whitePanel}</>
                ) : (
                  // 先手（黒）視点 / PvP: 白パネルが上/左、黒パネルが下/右
                  <>{whitePanel}{boardEl}{blackPanel}</>
                )}
              </div>
            );
          })()}
        </>
      )}

      {/* 取る / ツケる / 謀る 選択モーダル */}
      {pendingChoice && !boushouTargets && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl p-6 w-72 flex flex-col gap-4">
            <p className="text-center font-bold text-gray-800">どうしますか？</p>
            <p className="text-center text-sm text-gray-500">相手の駒の上に移動します</p>
            <button onClick={() => executeMove(pendingChoice.fromRow, pendingChoice.fromCol, pendingChoice.toRow, pendingChoice.toCol, "capture")}
              className="py-3 bg-red-600 text-white font-bold rounded-lg hover:bg-red-700 transition">取る（敵駒を除去）</button>
            <button onClick={() => executeMove(pendingChoice.fromRow, pendingChoice.fromCol, pendingChoice.toRow, pendingChoice.toCol, "tsuke_enemy")}
              className="py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 transition">ツケる（重ねる）</button>
            {pendingBoushouTargets.length > 0 && (
              <button
                onClick={() => setBoushouTargets(pendingBoushouTargets)}
                className="py-3 bg-purple-600 text-white font-bold rounded-lg hover:bg-purple-700 transition"
              >謀る（相手駒を寝返らせる）</button>
            )}
            <button onClick={() => setPendingChoice(null)} className="py-2 text-gray-500 text-sm hover:text-gray-800">キャンセル</button>
          </div>
        </div>
      )}

      {/* 謀り対象選択モーダル */}
      {pendingChoice && boushouTargets && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl p-6 w-72 flex flex-col gap-4">
            <p className="text-center font-bold text-gray-800">どの駒を寝返らせますか？</p>
            <p className="text-center text-sm text-gray-500">選んだ敵駒と手駒の同種駒が入れ替わります</p>
            {boushouTargets.map(({ index, piece }) => (
              <button
                key={index}
                onClick={() => executeBoushou(index)}
                className="py-3 bg-purple-600 text-white font-bold rounded-lg hover:bg-purple-700 transition"
              >
                {index === 0 ? "最下段" : `下から${index + 1}段目`}の「{piece.type}」を寝返らせる
              </button>
            ))}
            <button onClick={() => setBoushouTargets(null)} className="py-2 text-gray-500 text-sm hover:text-gray-800">
              ← 戻る
            </button>
          </div>
        </div>
      )}

      {/* スタック確認モーダル（凝モードでのタップ or 長押しで表示） */}
      {inspectStack !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setInspectCell(null)}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-64 flex flex-col gap-3" onClick={e => e.stopPropagation()}>
            <p className="text-center font-bold text-gray-800">スタック確認</p>
            <p className="text-center text-[10px] text-gray-400">タップ外・閉じるで戻る</p>
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
            <button onClick={() => setInspectCell(null)} className="py-2 bg-gray-100 text-gray-600 hover:bg-gray-200 rounded-lg text-sm font-medium transition">閉じる</button>
          </div>
        </div>
      )}

      {/* 観戦中は毎手画面が暗くならないよう、AI同士モードではオーバーレイを出さない */}
      {(loading || (aiThinking && gameState?.mode === "ai")) && (
        <div className="fixed inset-0 bg-black/10 flex items-center justify-center pointer-events-none">
          <div className="bg-white px-4 py-2 rounded shadow text-sm text-gray-600">
            {aiThinking ? "AI 思考中..." : "処理中..."}
          </div>
        </div>
      )}
    </main>
    {homeBtn}{homeConfirmModal}
    </>
  );
}
