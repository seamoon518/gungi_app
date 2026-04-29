# Phase A: 共通基盤の詳細設計

## 概要
AI対戦機能の基盤となるインターフェース、API、フロントエンド統合を整備する。このフェーズで作られたコンポーネントは Lv1〜3 すべてで共有される。

---

## A1. バックエンド：AI思考エンジン基盤

### ファイル構成
```
backend/logic/
├── ai_engine.py          [新規] AIエンジンの基本クラス・インターフェース
├── ai_evaluator.py       [新規] 評価関数（各フェーズで拡張）
└── (既存ファイルは変更なし)
```

### ai_engine.py の設計

```python
# インターフェース（実装の方向性）

class AIEngine:
    """αβ探索エンジンの基本クラス"""
    
    def __init__(self, difficulty: int):
        """difficulty: 1(Lv1), 2(Lv2), 3(Lv3)"""
        self.difficulty = difficulty
        self.evaluator = AIEvaluator(difficulty)
    
    def find_best_move(self, game_state: GameState, time_limit_sec: float) -> tuple[str, str]:
        """
        ゲーム状態からAIの最善手を探索する
        
        Args:
            game_state: 現在のゲーム状態
            time_limit_sec: 探索時間制限（秒）
        
        Returns:
            (from_pos, to_pos) - 盤面座標の文字列表現
                例: ("5,4", "5,5")
                例: ("hand_0", "3,3") - 手駒配置
        
        Raises:
            ValueError: ゲーム状態が異常、または合法手がない場合
        """
        pass
    
    def get_move_value(self, game_state: GameState, move: tuple) -> float:
        """指定の着手の評価値を返す（デバッグ用）"""
        pass
```

### ai_evaluator.py の設計

```python
# インターフェース（実装の方向性）

class AIEvaluator:
    """ゲーム状態の評価関数"""
    
    def __init__(self, difficulty: int):
        self.difficulty = difficulty  # 1,2,3
        self.weights = self._init_weights()
    
    def evaluate(self, game_state: GameState) -> float:
        """
        ゲーム状態を評価する（AIから見た評価値）
        
        戻り値の目安：
        - 正: AI（黒）有利
        - 負: 人間（白）有利
        - 大きいほど AI の勝利に近い
        
        Returns:
            float: 評価値（-inf ～ +inf）
        """
        pass
    
    def _init_weights(self) -> dict:
        """難易度に応じた重みづけをセット"""
        pass
```

---

## A2. バックエンド：API の新規エンドポイント

### 既存エンドポイント
`/game/{game_id}/move` でプレイヤー手を受け付けている。

### 新規エンドポイント

```
POST /game/{game_id}/ai-move
```

**説明**: AIの番の時、フロントから呼ばれてAIの着手を返す

**リクエスト**（バージョン1：簡潔）
```json
{}
```
（game_id とプレイヤー情報は既存のセッション管理で確認）

**レスポンス（成功時）**
```json
{
  "status": "ok",
  "from": "5,4",           // from座標（"row,col"形式）
  "to": "5,5",              // to座標
  "thinking_time_ms": 1234  // 実際の思考時間
}
```

**レスポンス（AI着手不可時）**
```json
{
  "status": "error",
  "message": "No legal moves or game already ended"
}
```

**処理フロー**
1. game_id から GameState を取得
2. `current_player` が AI か確認（黒=AI）
3. AIEngine.find_best_move() を呼び出す
4. GameEngine.apply_move() で着手を適用
5. 新しい盤面をレスポンス（既存の `/game/{game_id}/state` と統一）

---

## A3. フロントエンド：AI手番の自動処理

### 現状
`frontend/app/page.tsx` の GameBoard で、プレイヤーが手をクリックして指す。AI対戦モードでは「未実装」表示。

### 変更予定
- GameBoard に `ai_difficulty` (1,2,3) を渡す
- AI（黒）の番になったら自動で POST `/game/{game_id}/ai-move` を呼び出す
- 思考中はローディングスピナー表示
- AIの着手が返ってきたら、盤面を更新

### 実装パターン（案）

```typescript
// GameBoard.tsx の useEffect で
useEffect(() => {
  if (gameState.current_player === "black" && gameState.ai_difficulty > 0) {
    setIsThinking(true);
    
    // AIのムーブを取得
    const response = await fetch(`/api/game/${gameId}/ai-move`, {
      method: "POST",
    });
    const data = await response.json();
    
    // 盤面を更新（既存の getGameState() を呼んで再フェッチ）
    await refetchGameState();
    setIsThinking(false);
  }
}, [gameState.current_player, gameState.ai_difficulty]);
```

### UI
- AI思考中に `<LoadingSpinner />` を盤面に重ねる
- 「思考中...」「Lv{difficulty}が考えています」などのテキスト

---

## A4. 既存コードの確認事項

実装前に以下を確認・整理：

| 項目 | 場所 | 確認内容 |
|---|---|---|
| move座標の表現 | `/game/{game_id}/move` のリクエスト | "row,col" 文字列か？それとも数値配列か？ |
| 手駒配置の表現 | `backend/logic/rules.py` arata処理 | "hand_0", "hand_1", ... の表記法は確定か？ |
| 盤面ハッシュ | `board_hash()` 関数 | 千日手判定で使われている。探索でも流用可能か確認 |
| GameState の frozen? | `models/game_state.py` | frozen=True の dataclass であれば、探索時のコピー上書き時に注意 |
| エラーハンドリング | `backend/api/router.py` | 存在しない game_id、終了済みゲームへのアクセス時の処理 |

---

## A5. 実装の進め方（手順）

### Step 1: 基本骨組み（1〜2時間）
- `backend/logic/ai_engine.py` を スケルトン実装（メソッド定義のみ）
- `backend/logic/ai_evaluator.py` を スケルトン実装
- `backend/api/router.py` に `/game/{game_id}/ai-move` エンドポイント追加（ダミー手返却）
- テスト: 手動で curl で `/ai-move` を呼んで、応答を確認

### Step 2: フロントエンド統合（1〜2時間）
- `frontend/lib/api.ts` に `aiMove(gameId)` 関数を追加
- `frontend/components/GameBoard.tsx` に AI手番のロジック追加（useEffect）
- テスト: フロントから手動でボタンをクリックしてAIを呼び出し、ローディング表示確認

### Step 3: Lv1相当の簡易AIを実装（2〜3時間）
- `ai_evaluator.py` に「駒得のみ」の評価関数を実装
- `ai_engine.py` に「1手読みのαβ」を実装
- テスト: 何局か対局して、AIが本当に指しているか確認

この Step 3 まで完了すれば、「動く AI対戦」が完成し、以降は評価関数・探索深さを改善していく段階になる。

---

## A6. テスト方針

### ユニットテスト
- `test_ai_evaluator.py`: 同じ盤面で評価値が安定しているか
- `test_ai_engine.py`: 合法手のみを返すか、時間制限内に終わるか

### 統合テスト
- バックエンド: `/ai-move` エンドポイントが正常に手を返すか
- フロント: AI手番で自動で指され、盤面が更新されるか

### 対局テスト
- AI vs AI（自己対戦）で1局以上完走できるか
- 人間 vs AI で複数局、エラーが出ないか
- ゲーム終了後、リプレイなどで棋譜が正しいか

---

## A7. 注意点・リスク

1. **座標表記の一貫性**: move のリクエスト形式（文字列 vs 数値）が統一されていないと、バグの温床。実装前に既存コードで確認必須
2. **盤面コピーのパフォーマンス**: 探索で `copy.deepcopy()` を大量に呼ぶ。9×9×3層 = 243セル × 駒情報で遅延が出る可能性。要測定
3. **反復深化の実装**: Lv2以降で反復深化を使うため、時間制御の仕組みをここで先に設計しておくと、後の統合が楽
4. **ランダム性**: Lv1で「同点手から無作為選択」を入れるため、乱数シード の制御を考慮

