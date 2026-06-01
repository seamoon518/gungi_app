# バックエンド 引継ぎ資料 — 謀（ぼう）寝返り実装

## プロジェクト概要
- **アプリ名**: gungi_app（HUNTER×HUNTER「軍儀」ボードゲームのWebアプリ）
- **バックエンド**: Python / FastAPI
- **フロントエンド**: Next.js（別セッションで並行開発中）
- **デプロイ先**: Railway（https://gungiapp-production.up.railway.app）

---

## 現在のファイル構造

```
backend/
├── main.py                    # FastAPI アプリ
├── api/
│   ├── router.py              # エンドポイント定義（ここに追加）
│   └── schemas.py             # Pydantic スキーマ（ここに追加）
├── models/
│   ├── game_state.py          # GameState・GameRules データクラス
│   └── piece.py               # PieceType enum・Piece クラス
└── logic/
    ├── game_engine.py         # コアゲームロジック（ここに追加）
    ├── movement.py            # 合法手生成
    ├── rules.py               # apply_capture/apply_tsuke/apply_plain_move など
    ├── arata.py               # 手駒配置ロジック
    ├── setup.py               # 初期配置フェーズ
    └── ai/                    # AI思考エンジン（今回は無関係）
```

---

## 今回実装するタスク：謀（ぼう）の「寝返り」特殊能力

### ルール定義

| 項目 | 内容 |
|------|------|
| 発動条件 | 謀（BOU）を敵駒にツケた（tsuke_enemy）とき、スタック内の任意の敵駒と「同種の駒」を自分の手駒に持っている場合 |
| 効果 | 手駒の同種駒を選択した敵駒の位置（スタックインデックス）に置き換える。敵駒はゲームから除外 |
| スタック | 謀が最上段に残り、置き換えた自駒はその位置（下の段）に入る |
| 任意 | フロントエンドが「謀る」ボタン選択時のみ実行（発動しない選択も可能） |
| 複数対象 | スタック内に複数の敵駒がある場合、手駒と一致するものを任意に選べる |
| 自駒混在 | スタック内に自駒が混在していても、下層の敵駒に対しても適用可能 |

### スタック変換の例

```
before: [敵兵(0), 敵槍(1), 自砦(2)]  ←インデックス
謀が tsuke_enemy → [敵兵(0), 敵槍(1), 自砦(2), 自謀(3)]

target_index=1（敵槍）を選択、手駒に「槍」がある場合:
after:  [敵兵(0), 自槍(1), 自砦(2), 自謀(3)]
敵槍はゲームから除外、手駒の槍が消費される
```

---

## 実装する内容

### 1. `backend/api/schemas.py` — BoushouRequest 追加

```python
class BoushouRequest(BaseModel):
    from_row: int
    from_col: int
    to_row: int
    to_col: int
    target_index: int  # ツケ前のdestスタック内の敵駒インデックス（0=最下段）
```

---

### 2. `backend/logic/game_engine.py` — apply_boushou 追加

`_finish_turn`, `apply_move` などと同じファイルに追加。
既存の `apply_move` / `apply_arata` のパターンに倣うこと。

```python
def apply_boushou(
    state: GameState,
    from_row: int, from_col: int,
    to_row: int, to_col: int,
    target_index: int,
) -> Tuple[bool, str]:
    """謀（ぼう）の寝返りを実行する"""
    if state.game_over:
        return False, "Game is already over."
    if state.phase != "play":
        return False, "Not in play phase."

    # 1. 移動元の駒が謀であることを確認
    src_stack = state.board[from_row][from_col]
    if not src_stack:
        return False, "No piece at source."
    moving = src_stack[-1]
    if moving.type != PieceType.BOU:
        return False, "Moving piece is not 謀."
    if moving.owner != state.current_player:
        return False, "Not your piece."

    # 2. 移動先と対象インデックスのバリデーション
    dst_stack = state.board[to_row][to_col]
    if not dst_stack:
        return False, "No pieces at destination."
    if target_index < 0 or target_index >= len(dst_stack):
        return False, "Invalid target index."

    target_piece = dst_stack[target_index]
    player = state.current_player
    enemy = "white" if player == "black" else "black"
    if target_piece.owner != enemy:
        return False, "Target piece is not an enemy."

    # 3. 謀ツケが合法手であることを確認
    options = get_valid_moves(
        state.board, from_row, from_col,
        state.rules.max_stack, state.rules.sui_can_tsuke,
    )
    if (to_row, to_col) not in options.enemy_tsuke_moves:
        return False, "Boushou requires a valid tsuke_enemy move."

    # 4. 手駒に同種の駒があることを確認
    hand = state.hand_pieces[player]
    hand_idx = next((i for i, p in enumerate(hand) if p.type == target_piece.type), None)
    if hand_idx is None:
        return False, "No matching hand piece for boushou."

    # 5. 実行（deepcopy使用）
    new_board = copy.deepcopy(state.board)
    new_hand = {k: list(v) for k, v in state.hand_pieces.items()}

    # 手駒から同種駒を取り出す
    own_piece = new_hand[player].pop(hand_idx)

    # 謀を移動元から取り出す
    bou_piece = new_board[from_row][from_col].pop()

    # 敵駒を指定インデックスから除外（ゲームから永久に削除）
    new_board[to_row][to_col].pop(target_index)

    # 同位置に自駒を挿入（交換）
    new_board[to_row][to_col].insert(target_index, own_piece)

    # 謀をスタック最上段に追加
    new_board[to_row][to_col].append(bou_piece)

    state.board = new_board
    state.hand_pieces = new_hand
    state.move_history.append(Move(from_row, from_col, to_row, to_col))
    return _finish_turn(state, player)
```

---

### 3. `backend/api/router.py` — エンドポイント追加

```python
from logic.game_engine import (
    create_initial_state, apply_move, apply_arata,
    apply_setup_place, apply_setup_done,
    apply_boushou,  # ← 追加
)
from api.schemas import (
    NewGameRequest, MoveRequest, ValidMovesResponse,
    ArataRequest, ValidArataResponse, SetupPlaceRequest,
    BoushouRequest,  # ← 追加
)

@router.post("/{game_id}/boushou")
def boushou(game_id: str, req: BoushouRequest):
    """謀の寝返りを実行する"""
    state = _get_or_404(game_id)
    success, error = apply_boushou(
        state,
        req.from_row, req.from_col,
        req.to_row, req.to_col,
        req.target_index,
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return state.to_dict(game_id)
```

---

## 既存コードの重要パターン

### apply_move（参考）
`backend/logic/game_engine.py` にある。boushouも同じ構造で:
1. バリデーション（game_over, phase, 駒の所有確認）
2. `copy.deepcopy(state.board)` で新しいボードを作成
3. 操作を適用
4. `state.board = new_board` で差し替え
5. `state.move_history.append(...)` で履歴記録
6. `_finish_turn(state, player)` で手番切り替え・勝利判定

### PieceType
`backend/models/piece.py`:
- `PieceType.BOU` = `"謀"`
- `PieceType.SUI` = `"帅"` など

### hand_piecesの構造
```python
state.hand_pieces = {
    "black": [Piece(PieceType.SHO, "black"), ...],
    "white": [Piece(PieceType.YAR, "white"), ...],
}
```

---

## テスト方法

```python
# backend/test_boushou.py として作成して動作確認
from logic.game_engine import create_initial_state, apply_move, apply_boushou
from models.piece import PieceType, Piece

# 入門編でゲームを開始して謀を手動配置してテスト
# または直接ボードを組み立ててテスト
```

---

## 完了確認チェックリスト

- [ ] `BoushouRequest` を `schemas.py` に追加
- [ ] `apply_boushou` を `game_engine.py` に追加
- [ ] `POST /game/{id}/boushou` を `router.py` に追加
- [ ] `apply_boushou` のインポートを `router.py` に追加
- [ ] 手動テストで動作確認（スタック変換が正しいか）
- [ ] `python -c "from api.router import router; print('OK')"` でインポートエラーがないか確認

---

## フロントエンドとの調整事項

フロントエンド側（別セッション）は以下のAPIを呼び出す:

```
POST /game/{game_id}/boushou
Content-Type: application/json

{
  "from_row": 3,
  "from_col": 4,
  "to_row": 2,
  "to_col": 4,
  "target_index": 1
}

→ Response: GameState（通常のmove/arataと同じ形式）
```

**target_index** はツケ実行「前」のdestスタックのインデックス（0=最下段）。
