# AI強化① 評価関数チューニング 引継ぎ資料

## このセッションの目的
既存のalpha-beta AI の評価関数を改善し、各難易度の棋力を向上させる。
コードは `backend/logic/ai/` 以下のみ変更。他のファイルは基本的に触らない。

---

## プロジェクト情報

| 項目 | 内容 |
|------|------|
| バックエンド | Python 3.10, FastAPI |
| ローカル起動 | `cd backend && uvicorn main:app --reload --port 8002` |
| AI動作テスト | `cd backend && python test_ai.py` |

---

## 現在のAI実装（Phase B+C+E 完了）

### ファイル構成
```
backend/logic/ai/
├── engine.py      # 難易度別パラメータ・setupフェーズAI・ゲームAI呼び出し
├── evaluate.py    # 評価関数（Phase C）
└── search.py      # Alpha-beta探索本体（Phase E）
```

### 探索アルゴリズム（search.py）
- **Alpha-beta minimax** + 反復深化
- **置換表（TT）**: `TranspositionTable` クラス、最大300,000エントリ
- **静止探索（Quiescence Search）**: 深さ2、捕獲手のみ継続
- **Killer Heuristic**: 深さごとに2手保存
- **MVV-LVA**: 高価値の駒を取る手を優先
- **TT best-move first**: 前の深さの最善手を次の深さで先頭試行

### 難易度別パラメータ（engine.py）
```python
_DIFFICULTY_PARAMS = {
    "easy":   {"max_depth": 2, "time_limit": 1.0,  "noise": 80,  "max_moves": 25},
    "normal": {"max_depth": 4, "time_limit": 5.0,  "noise": 10,  "max_moves": 20},
    "hard":   {"max_depth": 6, "time_limit": 20.0, "noise": 0,   "max_moves": 15},
}
# 中級/上級(普通)はdepth = round(4 * 0.75) = 3
# 中級/上級(難しい)はdepth = round(6 * 1.0) = 6（TT効果で速い）
```

### 現在の評価関数（evaluate.py）
```python
def evaluate(state, ai_player):
    return (
        evaluate_material(state, ai_player)    # 駒得（手駒80%割引）
        + evaluate_position(state, ai_player)  # 位置・スタック・前進ボーナス
        + evaluate_sui_safety(state, ai_player)# 帅周囲の敵駒ペナルティ
    )
```

#### 駒の価値（PIECE_VALUES）
```python
SUI=100_000, TAI=700, CHU=600, OZU=550, TSU=500,
KIB=450, YAR=400, YUM=350, SAM=350, SHO=300,
SHI=300, BOU=300, TOR=250, HYO=100
```

---

## 改善タスク一覧

### Phase D: 棋力チューニング（最優先）

#### D1. 評価関数パラメータの調整
現状の問題：
- PIECE_VALUES は仮の値（実際の駒強度を反映していない可能性）
- 位置ボーナス（CENTER_BONUS × 3、前進 × 5/段）が適切かどうか不明
- 帅安全度のペナルティ（距離別 × 20）が強すぎ/弱すぎか未検証

調整方法：
1. AIどうしを自己対戦させる（`test_ai.py` に自己対戦機能を追加）
2. 勝率が 50/50 に近い評価パラメータを探す
3. 強い方向（難しい）が初級者に勝てるか人間でテスト

#### D2. 追加評価項目（実装候補）

**機動力評価（Mobility）**
```python
def evaluate_mobility(state, ai_player):
    # 合法手数が多い = 機動力が高い = 有利
    # get_all_game_moves() を呼ぶため計算コスト高い
    # → 深さ0のノードのみ適用を推奨
    ai_moves = len(get_all_game_moves(state, ai_player))
    human_moves = len(get_all_game_moves(state, opponent))
    return (ai_moves - human_moves) * 3
```

**脅威評価（Threat detection）**
```python
def evaluate_threats(state, ai_player):
    # 帅を1手で取れる状態なら大ボーナス/ペナルティ
    # → 計算コスト高い。easy/normalは省略可
```

**駒種別の位置テーブル**
現状: 全駒共通の CENTER_BONUS を使用
改善: 駒ごとに最適な位置が異なる（例: 帅は後方有利、槍は前方有利）
```python
PIECE_POSITION_BONUS = {
    PieceType.SUI: [[後方重視テーブル]],
    PieceType.YAR: [[前方重視テーブル]],
    ...
}
```

### Phase F: 強さ検証

#### 目標棋力
| レベル | 目標 |
|--------|------|
| 簡単 | ルールを覚えた人が数局で1勝できる |
| 普通 | 将棋ウォーズ4〜5級相当の戦術が必要 |
| 難しい | 中上級者が必要（初段は努力目標） |

#### 検証方法
1. `test_ai.py` に AI vs AI の自己対戦を追加
2. easy vs normal, normal vs hard で勝率を測定（各100局など）
3. 人間テスター（できれば複数人）に各難易度と対局してもらう
4. フィードバックをもとに PIECE_VALUES や重みを調整

---

## 実装上の注意点

### パフォーマンス
- `evaluate()` は探索の全ノードで呼ばれる → **できるだけ軽く保つ**
- `get_all_game_moves()` は1回のevaluate内で2回以上呼ばないこと（高コスト）
- 機動力評価を追加する場合は `depth == 0` のノードのみ適用すること

### 探索ファイルとの関係
```python
# search.py の葉ノード
if depth == 0:
    return quiescence(state, ai_player, alpha, beta, ...)

# quiescence の基底
stand_pat = evaluate(state, ai_player)  # ← ここで evaluate() が呼ばれる
```

### 評価値のスケール感
- 駒得が支配的: TAI(700) 1枚 ≈ HYO(100) 7枚
- 位置ボーナスは最大 ~30 点（CENTER_BONUS[4][4]=6 × 3 = 18）
- 帅安全度ペナルティ: 最大 -120 点（距離1の敵が3枚）
- → 評価値が駒得に対して小さすぎないか確認が必要

---

## テストスクリプト（backend/test_ai.py）

現状は各レベル×難易度の1手動作確認のみ。
以下を追加することを推奨：

```python
# AI自己対戦（追加推奨）
def ai_vs_ai(level, diff1, diff2, num_games=10):
    """diff1 vs diff2 の自己対戦。勝率を返す"""
    wins = {diff1: 0, diff2: 0, "draw": 0}
    for _ in range(num_games):
        # ゲームを最後まで進める
        ...
    return wins
```
