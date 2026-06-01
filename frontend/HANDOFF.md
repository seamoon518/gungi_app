# フロントエンド 引継ぎ資料 — 謀（ぼう）寝返りUI実装

## プロジェクト概要
- **アプリ名**: gungi_app（HUNTER×HUNTER「軍儀」ボードゲームのWebアプリ）
- **フロントエンド**: Next.js (App Router) / TypeScript / TailwindCSS
- **バックエンド**: FastAPI（別セッションで並行開発中）
- **デプロイ先**: Vercel（https://gungi-app.vercel.app）

---

## 現在のファイル構造（関連ファイルのみ）

```
frontend/
├── app/
│   └── page.tsx               # メインページ（ここを主に編集）
├── components/
│   ├── Board.tsx              # 9×9ボード表示
│   ├── Cell.tsx               # 単一セル表示
│   └── GameInfo.tsx           # 手駒・ボタン表示パネル
├── lib/
│   └── api.ts                 # バックエンドAPIクライアント（ここに追加）
└── types/
    └── game.ts                # TypeScript型定義（変更不要）
```

---

## 今回実装するタスク：謀（ぼう）の「寝返り」UI

### 現在の「どうしますか？」モーダルの動作

敵駒マスへの移動時に `pendingChoice` ステートが設定され、以下のモーダルが出る:
- **取る（敵駒を除去）** → `action="capture"` でAPI呼び出し
- **ツケる（重ねる）** → `action="tsuke_enemy"` でAPI呼び出し
- **キャンセル**

### 追加するUIフロー

```
[どうしますか？モーダル]（既存）
  ├── 取る（敵駒を除去）     ← 既存
  ├── ツケる（重ねる）       ← 既存
  ├── 謀る（相手駒を寝返らせる）  ← ★新規（条件を満たすときのみ表示）
  └── キャンセル             ← 既存

↓ 「謀る」を選択

[謀り対象選択モーダル]（★新規）
  「どの駒を寝返らせますか？」
  ├── 1段目（最下段）の「兵」を寝返らせる  ← 対象候補（該当するものだけ表示）
  ├── 2段目の「槍」を寝返らせる
  ├── （← 戻る）
  └── キャンセル
```

### 「謀る」ボタンの表示条件（フロントエンドで判定）

以下をすべて満たすとき表示:
1. 移動する駒（`selectedCell` の最上段駒）の `type === "謀"`
2. 移動先（`pendingChoice.toRow/toCol`）が `enemyTsukeMoves` に含まれている
3. 移動先スタック内に「プレイヤーの手駒と同種の敵駒」が1枚以上ある

---

## 実装手順

### 1. `frontend/lib/api.ts` — `boushou` メソッド追加

```typescript
boushou: (
  gameId: string,
  fromRow: number, fromCol: number,
  toRow: number, toCol: number,
  targetIndex: number,
): Promise<GameState> =>
  request(`/game/${gameId}/boushou`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      from_row: fromRow,
      from_col: fromCol,
      to_row: toRow,
      to_col: toCol,
      target_index: targetIndex,
    }),
  }),
```

---

### 2. `frontend/app/page.tsx` — 主な変更点

#### ステート追加（既存stateの近くに追加）

```typescript
// 謀り対象選択モーダル用
const [pendingBoushouTargets, setPendingBoushouTargets] = useState<
  { index: number; piece: Piece }[] | null
>(null);
```

#### `clearAll` に追加

```typescript
const clearAll = () => {
  // ... 既存の clearAll ...
  setPendingBoushouTargets(null);  // ← 追加
};
```

#### `executeBoushou` コールバック追加

```typescript
const executeBoushou = useCallback(async (targetIndex: number) => {
  if (!gameState || !pendingChoice) return;
  setLoading(true);
  setPendingBoushouTargets(null);
  setPendingChoice(null);
  try {
    const state = await api.boushou(
      gameState.game_id,
      pendingChoice.fromRow, pendingChoice.fromCol,
      pendingChoice.toRow, pendingChoice.toCol,
      targetIndex,
    );
    setGameState(state);
    clearAll();
  } catch (e) { setError(String(e)); }
  finally { setLoading(false); }
}, [gameState, pendingChoice]);
```

#### 謀る条件判定ヘルパー（render内で計算）

```typescript
// pendingChoice モーダルを表示している間に計算する
const boushouTargets: { index: number; piece: Piece }[] = (() => {
  if (!pendingChoice || !gameState) return [];
  // 移動駒が謀かチェック
  const srcStack = gameState.board[pendingChoice.fromRow][pendingChoice.fromCol].stack;
  if (!srcStack.length || srcStack[srcStack.length - 1].type !== "謀") return [];
  // ツケ先スタックの敵駒で、手駒と一致するものを抽出
  const destStack = gameState.board[pendingChoice.toRow][pendingChoice.toCol].stack;
  const enemy = gameState.current_player === "black" ? "white" : "black";
  const handTypes = new Set(
    (gameState.hand_pieces[gameState.current_player] ?? []).map(p => p.type)
  );
  return destStack
    .map((piece, index) => ({ index, piece }))
    .filter(({ piece }) => piece.owner === enemy && handTypes.has(piece.type));
})();

const showBoushouBtn = boushouTargets.length > 0;
```

---

### 3. JSX — 「どうしますか？」モーダルに謀るボタン追加

**変更前の該当部分**（`pendingChoice && (...)` のブロック）:
```tsx
{pendingChoice && (
  <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
    <div className="bg-white rounded-2xl shadow-xl p-6 w-72 flex flex-col gap-4">
      <p ...>どうしますか？</p>
      <p ...>相手の駒の上に移動します</p>
      <button onClick={capture}>取る（敵駒を除去）</button>
      <button onClick={tsuke}>ツケる（重ねる）</button>
      <button onClick={cancel}>キャンセル</button>
    </div>
  </div>
)}
```

**変更後**（謀るボタンを追加し、対象選択モーダルを分ける）:
```tsx
{/* 既存モーダル：謀るを追加 */}
{pendingChoice && !pendingBoushouTargets && (
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

      {/* ★ 謀るボタン（条件付き） */}
      {showBoushouBtn && (
        <button
          onClick={() => setPendingBoushouTargets(boushouTargets)}
          className="py-3 bg-purple-600 text-white font-bold rounded-lg hover:bg-purple-700 transition"
        >謀る（相手駒を寝返らせる）</button>
      )}

      <button onClick={() => setPendingChoice(null)} className="py-2 text-gray-500 text-sm hover:text-gray-800">
        キャンセル
      </button>
    </div>
  </div>
)}

{/* ★ 謀り対象選択モーダル（新規） */}
{pendingChoice && pendingBoushouTargets && (
  <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
    <div className="bg-white rounded-2xl shadow-xl p-6 w-72 flex flex-col gap-4">
      <p className="text-center font-bold text-gray-800">どの駒を寝返らせますか？</p>
      <p className="text-center text-sm text-gray-500">
        選んだ敵駒と手駒の同種駒が入れ替わります
      </p>
      {pendingBoushouTargets.map(({ index, piece }) => (
        <button
          key={index}
          onClick={() => executeBoushou(index)}
          className="py-3 bg-purple-600 text-white font-bold rounded-lg hover:bg-purple-700 transition"
        >
          {index === 0 ? "最下段" : `下から${index + 1}段目`}の「{piece.type}」を寝返らせる
        </button>
      ))}
      <button
        onClick={() => setPendingBoushouTargets(null)}
        className="py-2 text-gray-500 text-sm hover:text-gray-800"
      >← 戻る</button>
    </div>
  </div>
)}
```

---

## 完了確認チェックリスト

- [ ] `api.ts` に `boushou()` メソッド追加
- [ ] `page.tsx` に `pendingBoushouTargets` state追加
- [ ] `clearAll` に `setPendingBoushouTargets(null)` 追加
- [ ] `executeBoushou` コールバック追加
- [ ] `boushouTargets` / `showBoushouBtn` の計算ロジック追加
- [ ] 既存「どうしますか？」モーダルに謀るボタン追加
- [ ] 謀り対象選択モーダルを追加
- [ ] TypeScript型チェック（`npx tsc --noEmit`）でエラーがないか確認

---

## バックエンドAPIとの調整事項

バックエンド側（別セッション）が実装するエンドポイント:

```
POST /game/{game_id}/boushou
{
  "from_row": int,     // 謀がいる行
  "from_col": int,     // 謀がいる列
  "to_row": int,       // ツケ先の行
  "to_col": int,       // ツケ先の列
  "target_index": int  // ツケ前のdestスタック内の敵駒インデックス（0=最下段）
}
→ Response: GameState（通常のmove/arataと同じ形式）
```

**target_index** はツケ実行「前」の destスタックのインデックス。
フロントエンドは `gameState.board[toRow][toCol].stack` のインデックスをそのまま送ればOK。

---

## 既存コードの重要パターン

### executeMove（参考）
```typescript
const executeMove = useCallback(async (fromRow, fromCol, toRow, toCol, action) => {
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
```
`executeBoushou` も同じパターンで実装すること。

### Piece型
```typescript
// frontend/types/game.ts
export type PieceType = "帥" | "大" | "中" | "小" | "侍" | "槍" | "馬" | "忍" | "砦" | "兵" | "砲" | "筒" | "弓" | "謀";
export interface Piece { type: PieceType; owner: Player; }
```
