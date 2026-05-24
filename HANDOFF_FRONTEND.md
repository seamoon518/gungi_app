# フロントエンド改修 引継ぎ資料

## このセッションの目的
gungi_app フロントエンドのUI/UX改善。ゲームロジックやAPIは変更しない。

---

## プロジェクト情報

| 項目 | 内容 |
|------|------|
| フロントエンド | Next.js (App Router), TypeScript, TailwindCSS |
| 本番URL | https://gungi-app.vercel.app |
| バックエンドURL | https://gungiapp-production.up.railway.app |
| ローカル起動 | `cd frontend && npm run dev` → http://localhost:3000 |
| 型チェック | `cd frontend && npx tsc --noEmit` |

---

## 現在のファイル構造

```
frontend/
├── app/
│   └── page.tsx          # 全画面（タイトル/モード選択/ゲーム）を1ファイルで管理
├── components/
│   ├── Board.tsx         # 9×9ボード（レスポンシブ列幅: w-9/w-11/w-14）
│   ├── Cell.tsx          # セル（w-9/w-11/w-14 でレスポンシブ、駒はinset-[10%]で中央配置）
│   └── GameInfo.tsx      # 手駒・凝・投了ボタン（w-full lg:w-44）
├── lib/
│   └── api.ts            # バックエンドAPIクライアント
└── types/
    └── game.ts           # 型定義（GameState, PieceType など）
```

---

## 現在の画面フロー

```
title → mode_select → pvp_rule_select → game
                    ↘ ai_difficulty_select → ai_rule_select → game
```

---

## 実装済みUI機能

- レスポンシブボード（mobile: 36px, sm: 44px, lg: 56px セル）
- 白駒 180°回転表示（敵駒の向きが逆）
- 最終手ハイライト（水色 bg-sky-200）
- タイトルに戻るボタン（全画面右上固定・確認モーダル）
- 白陣パネル（左、lg以上で回転）/ 黒陣パネル（右）
- AI思考中ローディング表示
- 謀る選択モーダル（取る/ツケる/謀る の3択）
- 初期配置フェーズUI（済を宣言ボタン・配置状況表示）

---

## 改善候補（優先度高）

### 1. ゲーム終了演出
現在: 上部に小さいテキスト表示のみ
改善案:
- 勝利/敗北/引き分けのフルスクリーン演出
- 「もう一度」ボタンを目立つ場所に配置
- 対局結果のサマリー（手数など）

### 2. 操作フィードバックの向上
- 駒を選択したときのアニメーション
- 移動確定時の軽いアニメーション
- 謀の寝返り成功時のエフェクト

### 3. モバイルUI継続改善
- 凝モードのスタック表示（現在lg以上のみ）→ モバイルでも利用できる別UIを検討
- タッチ操作の精度向上

### 4. AI対戦中の表示改善
- AI思考中のより明確なインジケーター
- AI が打った手のハイライト（現在最終手ハイライトで対応済みだが強調度を上げる）

### 5. ゲーム情報の充実
- 手数カウント表示（現在は move_count があるが小さく表示）
- 捕獲・除外された駒の一覧表示

---

## 改善候補（優先度中）

- ダークモード対応
- アクセシビリティ（キーボード操作、スクリーンリーダー対応）
- オンボーディング（初回プレイ時のルール説明）
- BGM/効果音（optional）

---

## 重要な実装パターン

### ゲーム状態（GameState型）
```typescript
// frontend/types/game.ts
interface GameState {
  game_id: string;
  board: Cell[][];         // board[row][col].stack = Piece[]
  current_player: Player;  // "black" | "white"
  hand_pieces: Record<Player, Piece[]>;
  game_over: boolean;
  winner: Player | null;
  move_count: number;
  level: GameLevel;        // "nyumon"|"shokyuu"|"chukyuu"|"joukyuu"
  mode: GameMode;          // "pvp"|"ai"
  phase: "setup" | "play";
  setup_done: Record<Player, boolean>;
  ai_player: Player | null;
  last_move: { from_row, from_col, to_row, to_col } | null;
}
```

### APIクライアント（api.ts）
```typescript
// 主なメソッド
api.newGame(level, mode, aiDifficulty)
api.move(gameId, fromRow, fromCol, toRow, toCol, action)
api.arata(gameId, pieceType, toRow, toCol)
api.boushou(gameId, fromRow, fromCol, toRow, toCol, targetIndex)
api.setupPlace(gameId, pieceType, toRow, toCol)
api.setupDone(gameId)
api.aiMove(gameId)
```

### Tailwindブレークポイント
- `sm`: 640px以上
- `lg`: 1024px以上（パネル横並びはlg以上）

---

## 注意事項

- `page.tsx` は現在500行超の1ファイル。大きな改修時はコンポーネント分割を検討
- `Cell.tsx` の駒サイズはブレークポイントで変わるため、px固定値は使わない（`inset-[10%]`で対応済み）
- `GameInfo.tsx` に `isAiControlled` フラグあり（AI担当プレイヤーは手駒クリック無効）
