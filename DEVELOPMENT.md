# 開発進捗サマリー

**最終更新**: 2026-05-18（セッション3終了時点）

---

## 📌 プロジェクト概要

**アプリ名**: gungi_app  
**説明**: HUNTER×HUNTERに登場する思考型ボードゲーム「軍議」のWebアプリ  
**デプロイ**:
- フロントエンド: https://gungi-app.vercel.app（Vercel）
- バックエンド: https://gungiapp-production.up.railway.app（Railway）

### テックスタック
| 層 | 技術 |
|---|---|
| フロントエンド | Next.js (App Router), TypeScript, TailwindCSS |
| バックエンド | Python 3.10, FastAPI, Pydantic v2 |
| デプロイ | Vercel（FE）, Railway（BE）|

### 起動方法
```bash
# バックエンド（ポート8002 ※8000/8001は他アプリが使用中）
cd backend && uvicorn main:app --reload --port 8002

# フロントエンド
cd frontend && npm run dev
# → http://localhost:3000
```

---

## ✅ 実装済み機能（全体）

### ゲームルール
| ルール | 状態 |
|--------|------|
| 駒の移動（全14種類） | ✅ |
| ツケ（スタック）・段数制限 | ✅ |
| 取る（捕獲・スタック処理） | ✅ |
| 飛び越し（砲・筒・弓） | ✅ |
| 手駒配置（新・あらた） | ✅ |
| 師ツケ制限（入門/初級:なし, 中級/上級:あり） | ✅ |
| 初期配置フェーズ（中級/上級）| ✅ |
| 千日手 | ✅ |
| 謀（ぼう）の寝返り | ✅ |
| 勝利・投了判定 | ✅ |

### レベル別ルール
| レベル | 初期配置 | 特殊駒 | ツケ段数 | 師ツケ |
|--------|---------|--------|---------|--------|
| 入門編 | 確定 | なし | 2段 | なし |
| 初級編 | 確定 | 弓のみ | 2段 | なし |
| 中級編 | 自由 | あり | 2段 | あり |
| 上級編 | 自由 | あり | 3段 | あり |

### フロントエンド
- ✅ タイトル → モード選択 → 難易度選択 → ルール選択 → ゲーム画面
- ✅ PvP / AI対戦モード
- ✅ レスポンシブUI（スマホ対応：セルサイズ可変）
- ✅ 駒の向き表示（白駒180°回転）
- ✅ 最終手ハイライト（水色）
- ✅ タイトルに戻るボタン（全画面・確認モーダル）
- ✅ 両プレイヤーパネル（白:左/回転, 黒:右）
- ✅ 謀る選択モーダル（3択: 取る/ツケる/謀る）

### AI
- ✅ Alpha-beta探索（反復深化）
- ✅ 置換表（Transposition Table）
- ✅ 静止探索（Quiescence Search）
- ✅ Killer Heuristic + MVV-LVA
- ✅ 評価関数: 駒得 + 位置 + 帅安全度 + スタック価値
- ✅ 全12パターン（4レベル × 3難易度）動作確認済み

---

## 🚀 残タスク（次セッション向け）

### 1. フロントエンド改修（詳細: `HANDOFF_FRONTEND.md`）
- UI/UX改善（アニメーション、ゲーム終了演出など）
- モバイルUI継続改善
- アクセシビリティ

### 2. AI強化① 評価関数チューニング（詳細: `HANDOFF_AI_EVAL.md`）
- Phase D: 評価関数パラメータ調整
- Phase F: 人間対局による棋力検証
- 評価項目の追加（機動力・駒の連携・脅威評価）

### 3. AI強化② 機械学習アプローチ（詳細: `HANDOFF_AI_ML.md`）
- AlphaZero型（自己対戦 + NN）の設計
- 長期プロジェクト（GPU費・実装コスト考慮）

---

## 📂 ディレクトリ構造（現在）

```
gungi_app/
├── backend/
│   ├── main.py                    # FastAPI アプリ
│   ├── Procfile                   # Railway起動コマンド
│   ├── railway.toml               # Railway設定
│   ├── requirements.txt
│   ├── test_ai.py                 # AI動作確認スクリプト
│   ├── api/
│   │   ├── router.py              # エンドポイント（11個）
│   │   └── schemas.py             # Pydanticスキーマ
│   ├── models/
│   │   ├── game_state.py          # GameState, GameRules
│   │   └── piece.py               # PieceType enum, Piece
│   └── logic/
│       ├── game_engine.py         # コアロジック（移動・配置・寝返り）
│       ├── movement.py            # 合法手生成（ルール別パラメータ対応）
│       ├── piece_moves.py         # 駒別移動パターン定義
│       ├── arata.py               # 手駒配置ロジック
│       ├── rules.py               # apply_capture/tsuke/plain_move
│       ├── setup.py               # 初期配置フェーズ
│       └── ai/
│           ├── engine.py          # AI入口（難易度・レベル別パラメータ）
│           ├── evaluate.py        # 評価関数（Phase C）
│           └── search.py          # Alpha-beta + TT + Quiescence
│
├── frontend/
│   ├── app/
│   │   └── page.tsx               # メインページ（全画面・ゲームロジック）
│   ├── components/
│   │   ├── Board.tsx              # 9×9ボード
│   │   ├── Cell.tsx               # セル（レスポンシブサイズ）
│   │   └── GameInfo.tsx           # 手駒・ボタンパネル
│   ├── lib/
│   │   └── api.ts                 # APIクライアント
│   └── types/
│       └── game.ts                # TypeScript型定義
│
├── DEVELOPMENT.md                 # このファイル
├── HANDOFF_FRONTEND.md            # フロントエンドセッション引継ぎ
├── HANDOFF_AI_EVAL.md             # AI評価関数セッション引継ぎ
├── HANDOFF_AI_ML.md               # AI機械学習セッション引継ぎ
├── gungi_rule.md                  # ゲームルール仕様書
└── .gitignore
```

---

## ⚠️ 重要な実装上の注意点

1. **帅（スイ）の上に他の駒は積めない**（絶対ルール）
2. **捕獲した駒はゲームから除外**（手駒に入らない。将棋と異なる）
3. **謀の寝返り**: tsuke_enemy後のスタックで、手駒と同種の敵駒を置き換える
4. **ポート**: ローカルはバックエンド8002（8000/8001は他アプリが使用）
5. **Railway Root Directory**: `backend` に設定必須（プッシュ後にリセットされることあり）
