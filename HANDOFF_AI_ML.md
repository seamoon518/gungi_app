# AI強化② 機械学習アプローチ 引継ぎ資料

## このセッションの目的
alpha-beta AIを超える強さを目指すための機械学習（AlphaZero型）アプローチを設計・実装する。
長期プロジェクト。**このセッションは設計・PoC段階**を想定。

---

## 前提条件（このセッション開始前に確認）

- [ ] 既存の alpha-beta AI（HANDOFF_AI_EVAL.md）のチューニングが完了していること
- [ ] 自己対戦スクリプト（AI vs AI）が動作すること（学習データ生成に必要）
- [ ] GPU環境またはクラウド学習環境の確認（Google Colab, Vast.ai など）

---

## 要件（ai-cozy-blanket.md より抜粋）

| 項目 | 内容 |
|------|------|
| 開発費上限 | ¥10万 |
| 運用費 | 100対局あたり¥1,000以下 |
| 目標棋力 | 将棋ウォーズ初段以上（努力目標） |
| 採用しない | Gemini API（コスト・安定性の問題） |
| 将来候補 | AlphaZero型（GPU費数千〜1万円、実装1〜2ヶ月） |

---

## 技術方針：AlphaZero型アプローチ

### アーキテクチャ概要

```
[自己対戦データ生成]    [ニューラルネット]    [MCTS探索]
  alpha-beta AI    →   Policy Network    →  強化された探索
  自己対戦        →   Value Network     →  より強い指し手
```

### コンポーネント

| コンポーネント | 役割 | 実装難度 |
|--------------|------|---------|
| Self-play engine | 自己対戦でデータ生成 | 中 |
| Policy Network | どの手を指すかの確率 | 高 |
| Value Network | 局面の評価値 | 高 |
| MCTS | NNガイドのモンテカルロ探索 | 高 |
| 学習ループ | データ生成→学習→強化の繰り返し | 高 |

---

## 実装ロードマップ

### Step 1: データ生成基盤（優先実装）
既存の alpha-beta AI を使って対局データを生成。

```python
# backend/logic/ai/self_play.py
def generate_self_play_games(num_games: int, level: str) -> list[dict]:
    """
    AI同士の自己対戦を行い、学習データを生成する。
    各局面について (board_state, move_played, outcome) を記録。
    """
```

出力形式（各ゲーム）:
```json
{
  "moves": [
    {
      "board": "...(盤面のシリアライズ)",
      "move": {"from_row": 6, "from_col": 4, "to_row": 5, "to_col": 4},
      "player": "black"
    }
  ],
  "winner": "black"
}
```

### Step 2: 盤面の特徴量エンジニアリング
NNへの入力として盤面を数値化。

```python
# board を numpy array に変換
# shape: (channels, 9, 9)
# channels:
#   0-13: 各駒種（自軍）の存在 (0 or 1)
#   14-27: 各駒種（敵軍）の存在 (0 or 1)
#   28-30: スタック高さ (1段/2段/3段)
#   31: 現在の手番 (0 or 1)
#   32-34: 自軍手駒の各駒数
#   35-37: 敵軍手駒の各駒数
# 合計: ~38 channels
```

### Step 3: ニューラルネット設計

```python
# PyTorchで実装
# ResNet型 (畳み込みブロック × 10〜20)

class GungiNet(nn.Module):
    def __init__(self):
        self.conv_blocks = nn.Sequential(
            # 共有の特徴抽出
            ResBlock(in_channels=38, out_channels=256),
            ...
        )
        self.policy_head = nn.Linear(256 * 9 * 9, num_moves)  # 全合法手数
        self.value_head = nn.Linear(256, 1)  # 勝率 (-1 to 1)
```

### Step 4: MCTS実装
NNのpolicy/valueを使ったモンテカルロ木探索。

```python
class MCTSNode:
    visits: int
    value_sum: float
    prior: float  # policy network の出力
    children: dict  # move → MCTSNode
```

### Step 5: 学習ループ
```
1. alpha-beta AI で初期データ生成（1,000〜10,000局）
2. NNを学習（supervised learning）
3. MCTS + NN で自己対戦（より良いデータ）
4. NNを更新（reinforcement learning）
5. 3〜4を繰り返す
```

---

## 実装上の判断ポイント

### Q1. alpha-beta AI を完全に捨てるか？
**推奨**: 段階的移行。
- Lv1/Lv2 は alpha-beta を維持（軽量・安定）
- Lv3 のみ MCTS + NN に置き換え
- コスト効率が高く、既存ユーザーへの影響も小さい

### Q2. デプロイ環境
現在のRailway（无料/低コストプラン）では GPU推論は困難。
選択肢：
1. **CPUでの軽量推論**（小さいNN）: Railway継続可能
2. **VPS（GPU付き）**: 月額数千〜数万円
3. **WebAssembly**（ブラウザで推論）: サーバーコスト¥0だが実装難度高

### Q3. 軍儀固有の課題
- **可変の手数**: 合法手数が局面によって大きく異なる（5〜100手以上）
- **スタック**: 3次元的な盤面表現が必要
- **手駒**: 盤外の状態（手駒）も評価に必要
- **学習データ不足**: 軍儀の棋譜データが公開されていない → 自己対戦が唯一のデータソース

---

## 既存資産の再利用

| 資産 | 再利用方法 |
|------|-----------|
| `get_all_game_moves()` | MCTSの子ノード展開 |
| `get_winner()` | ゲーム終了判定 |
| `board_hash()` | 重複局面検出 |
| `evaluate()` | 初期のValue network の教師信号 |
| alpha-beta AI | 初期データ生成・ベースライン比較 |

---

## 開発環境準備

```bash
# 必要なパッケージ（追加）
pip install torch torchvision numpy

# または
pip install tensorflow numpy
```

ファイル配置案：
```
backend/logic/ai/
├── engine.py      # 既存（alpha-beta）
├── evaluate.py    # 既存（評価関数）
├── search.py      # 既存（alpha-beta探索）
├── self_play.py   # 新規：自己対戦データ生成
├── features.py    # 新規：盤面の特徴量変換
├── model.py       # 新規：ニューラルネット定義
├── mcts.py        # 新規：MCTS実装
└── train.py       # 新規：学習ループ
```

---

## このセッションでのゴール（現実的）

1. `features.py` — 盤面 → numpy array 変換を完成
2. `self_play.py` — alpha-beta での自己対戦データ生成を完成
3. `model.py` — 小さなResNetを定義（PoC用）
4. 小規模な学習実験（100局程度のデータで過学習確認）
5. alpha-beta と比較して方向性を確認

完全な強さへの到達は複数セッション（数週間〜数ヶ月）を要する。
