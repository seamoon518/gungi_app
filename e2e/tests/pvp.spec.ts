import { test, expect, Page, TestInfo } from "@playwright/test";
import {
  cell, cellClass, longPress, panel, press, startPvp, topPiece, trackApi, isTouch, GameStateJson,
} from "./helpers";

async function mv(page: Page, ti: TestInfo, fr: number, fc: number, tr: number, tc: number) {
  await press(cell(page, fr, fc), ti);
  await expect(cell(page, tr, tc)).toHaveClass(/bg-green-200/);
  await press(cell(page, tr, tc), ti);
  await expect.poll(() => topPiece(page, fr, fc)).toBe("");
}

test.describe("C: プレイヤー同士", () => {
  test("C1 駒選択 → 移動可能マス → 移動", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await press(cell(page, 6, 0), ti);
    await expect(cell(page, 6, 0)).toHaveClass(/bg-yellow-300/);
    await expect(cell(page, 5, 0)).toHaveClass(/bg-green-200/);
    await expect(cell(page, 7, 0)).toHaveClass(/bg-green-200/);
    await press(cell(page, 5, 0), ti);
    await expect.poll(() => topPiece(page, 5, 0)).toBe("兵");
    expect(await topPiece(page, 6, 0)).toBe("");
    await expect(cell(page, 5, 0)).toHaveClass(/bg-sky-200/); // 最終手
    await expect(panel(page, "white")).toContainText("▶ 手番");
  });

  test("C2 敵駒への移動: キャンセル / ツケる / 取る", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await mv(page, ti, 6, 4, 5, 4);
    await mv(page, ti, 2, 4, 3, 4);
    await mv(page, ti, 5, 4, 4, 4);
    // 白: (3,4) → (4,4) の黒兵へ
    await press(cell(page, 3, 4), ti);
    await press(cell(page, 4, 4), ti);
    await expect(page.getByText("どうしますか？")).toBeVisible();
    await press(page.getByRole("button", { name: "キャンセル" }), ti);
    await expect(page.getByText("どうしますか？")).toBeHidden();
    expect(await topPiece(page, 3, 4)).toBe("兵");
    await press(cell(page, 4, 4), ti);
    await press(page.getByRole("button", { name: /ツケる/ }), ti);
    await expect(cell(page, 4, 4)).toContainText("2");      // 2段
    await expect(cell(page, 4, 4).locator("div").first()).toHaveClass(/ring-blue-400/);
  });

  test("C2b 取る", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await mv(page, ti, 6, 4, 5, 4);
    await mv(page, ti, 2, 4, 3, 4);
    await mv(page, ti, 5, 4, 4, 4);
    await press(cell(page, 3, 4), ti);
    await press(cell(page, 4, 4), ti);
    await press(page.getByRole("button", { name: /取る/ }), ti);
    await expect.poll(() => topPiece(page, 3, 4)).toBe("");
    await expect(cell(page, 4, 4)).not.toContainText("2");
    // 白駒は回転表示
    await expect(cell(page, 4, 4).locator("div").first()).toHaveClass(/rotate-180/);
  });

  test("C4 手駒を打つ（新）", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    const sho = panel(page, "black").getByRole("button", { name: /^小/ });
    await expect(sho).toContainText("2");
    await press(sho, ti);
    await expect(cell(page, 7, 0)).toHaveClass(/bg-purple-200/);
    await expect(cell(page, 5, 0)).not.toHaveClass(/bg-purple-200/); // 最前列より前は不可
    await press(cell(page, 7, 0), ti);
    await expect.poll(() => topPiece(page, 7, 0)).toBe("小");
    await expect(sho).not.toContainText("2");
  });

  test("C5 相手駒タップで移動範囲プレビュー", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await press(cell(page, 2, 0), ti);
    await expect(cell(page, 2, 0)).toHaveClass(/bg-rose-200/);
    await expect(cell(page, 3, 0)).toHaveClass(/bg-red-100/);
    await press(cell(page, 2, 0), ti);
    await expect(cell(page, 2, 0)).not.toHaveClass(/bg-rose-200/);
  });

  test("C6 凝モード / 長押しでスタック確認", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await press(panel(page, "black").getByRole("button", { name: "凝" }), ti);
    await expect(panel(page, "black").getByRole("button", { name: "凝 ON" })).toBeVisible();
    await press(cell(page, 8, 4), ti);
    await expect(page.getByText("スタック確認")).toBeVisible();
    await expect(page.locator("p.text-xs.font-semibold", { hasText: "帥" })).toBeVisible();
    await press(page.getByRole("button", { name: "閉じる" }), ti);
    await expect(page.getByText("スタック確認")).toBeHidden();
    await press(panel(page, "black").getByRole("button", { name: "凝 ON" }), ti);

    if (isTouch(ti)) {
      // F4: 長押しで開き、指を離しても閉じない
      await longPress(page, cell(page, 6, 0));
      await expect(page.getByText("スタック確認")).toBeVisible();
      await page.waitForTimeout(800);
      await expect(page.getByText("スタック確認")).toBeVisible();
      // 長押しでは駒が選択されない
      await press(page.getByRole("button", { name: "閉じる" }), ti);
      expect(await cellClass(page, 6, 0)).not.toContain("bg-yellow-300");
    }
  });

  test("C7 待った・投了・終局表示", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await mv(page, ti, 6, 0, 5, 0);
    await press(panel(page, "white").getByRole("button", { name: "待った" }), ti);
    await expect.poll(() => topPiece(page, 6, 0)).toBe("兵");
    expect(await topPiece(page, 5, 0)).toBe("");
    await expect(panel(page, "black")).toContainText("▶ 手番");
    await press(panel(page, "black").getByRole("button", { name: "投了" }), ti);
    await expect(page.getByText("ゲーム終了")).toBeVisible();
    await expect(page.getByText("白陣 の勝利！")).toBeVisible();
    // 終局後は駒を動かせない
    await press(cell(page, 6, 0), ti);
    expect(await cellClass(page, 6, 0)).not.toContain("bg-yellow-300");
  });

  test("C8 中級編の初期配置フェーズ", async ({ page }, ti) => {
    await startPvp(page, "中級編", ti);
    await expect(page.getByText("初期配置フェーズ")).toBeVisible();
    await expect(page.getByText("まず帥（スイ）を自陣に配置してください")).toBeVisible();
    await press(panel(page, "black").getByRole("button", { name: /^大/ }), ti);
    await expect(panel(page, "black")).toContainText("帥を先に配置してください。");
    await press(panel(page, "black").getByRole("button", { name: /^帥/ }), ti);
    await expect(cell(page, 6, 0)).toHaveClass(/bg-purple-200/);
    await expect(cell(page, 5, 0)).not.toHaveClass(/bg-purple-200/);
    await press(cell(page, 8, 4), ti);
    await expect.poll(() => topPiece(page, 8, 4)).toBe("帥");
    await press(panel(page, "white").getByRole("button", { name: /^帥/ }), ti);
    await press(cell(page, 0, 4), ti);
    await expect.poll(() => topPiece(page, 0, 4)).toBe("帥");
    await press(panel(page, "black").getByRole("button", { name: "済を宣言" }), ti);
    await expect(page.getByText("黒: 済 ✓")).toBeVisible();
    // 黒が済 → 白が続けて配置できる
    await press(panel(page, "white").getByRole("button", { name: /^大/ }), ti);
    await press(cell(page, 0, 3), ti);
    await expect.poll(() => topPiece(page, 0, 3)).toBe("大");
    await expect(panel(page, "white")).toContainText("配置中");
    await press(panel(page, "white").getByRole("button", { name: "済を宣言" }), ti);
    await expect(page.getByText("初期配置フェーズ")).toBeHidden();
    await expect(panel(page, "black")).toContainText("▶ 手番");
  });
});

// ── C3: 謀の寝返り（API をモックして盤面を用意） ─────────────────────────────

function emptyBoard() {
  return Array.from({ length: 9 }, () => Array.from({ length: 9 }, () => ({ stack: [] as any[] })));
}

function mockState(overrides: Partial<GameStateJson> = {}): GameStateJson {
  const board = emptyBoard();
  board[5][4].stack = [{ type: "謀", owner: "black" }];
  board[4][3].stack = [{ type: "兵", owner: "white" }];
  board[8][0].stack = [{ type: "帥", owner: "black" }];
  board[0][8].stack = [{ type: "帥", owner: "white" }];
  return {
    game_id: "mock-bou", board, current_player: "black",
    hand_pieces: { black: [{ type: "兵", owner: "black" }], white: [] },
    game_over: false, winner: null, move_count: 10, phase: "play", mode: "pvp", ai_player: null,
    ...({ level: "chukyuu", setup_done: { black: true, white: true }, ai_difficulty_black: null,
      ai_difficulty_white: null, last_move: null } as any),
    ...overrides,
  };
}

test("C3 謀る → 対象選択 → 実行", async ({ page }, ti) => {
  let boushouBody: any = null;
  await page.route("**/game/new", (r) => r.fulfill({ json: mockState() }));
  await page.route("**/game/mock-bou/valid-moves**", (r) =>
    r.fulfill({ json: { valid_moves: [[4, 3], [4, 5], [6, 4]], enemy_tsuke_moves: [[4, 3]] } }));
  await page.route("**/game/mock-bou/boushou", async (r) => {
    boushouBody = r.request().postDataJSON();
    const after = mockState({ current_player: "white", move_count: 11 } as any);
    after.board[5][4].stack = [];
    after.board[4][3].stack = [{ type: "兵", owner: "black" }, { type: "謀", owner: "black" }];
    after.hand_pieces.black = [];
    await r.fulfill({ json: after });
  });
  await startPvp(page, "中級編", ti);
  await press(cell(page, 5, 4), ti);
  await press(cell(page, 4, 3), ti);
  await expect(page.getByText("どうしますか？")).toBeVisible();
  await press(page.getByRole("button", { name: /謀る/ }), ti);
  await expect(page.getByText("どの駒を寝返らせますか？")).toBeVisible();
  // 戻る → 元のモーダル
  await press(page.getByRole("button", { name: "← 戻る" }), ti);
  await expect(page.getByText("どうしますか？")).toBeVisible();
  await press(page.getByRole("button", { name: /謀る/ }), ti);
  await press(page.getByRole("button", { name: "最下段の「兵」を寝返らせる" }), ti);
  await expect.poll(() => boushouBody).toEqual({ from_row: 5, from_col: 4, to_row: 4, to_col: 3, target_index: 0 });
  await expect.poll(() => topPiece(page, 4, 3)).toBe("謀");
  await expect(cell(page, 4, 3)).toContainText("2");
});

test("C3b 手駒に同種がなければ謀るボタンは出ない", async ({ page }, ti) => {
  const st = mockState();
  st.hand_pieces.black = [{ type: "小", owner: "black" }];
  await page.route("**/game/new", (r) => r.fulfill({ json: st }));
  await page.route("**/game/mock-bou/valid-moves**", (r) =>
    r.fulfill({ json: { valid_moves: [[4, 3]], enemy_tsuke_moves: [[4, 3]] } }));
  await startPvp(page, "中級編", ti);
  await press(cell(page, 5, 4), ti);
  await press(cell(page, 4, 3), ti);
  await expect(page.getByText("どうしますか？")).toBeVisible();
  await expect(page.getByRole("button", { name: /謀る/ })).toHaveCount(0);
});

test("F3 素早い連続タップでも移動リクエストは 1 回だけ", async ({ page }, ti) => {
  const log = trackApi(page);
  await startPvp(page, "入門編", ti);
  await press(cell(page, 6, 0), ti);
  await expect(cell(page, 5, 0)).toHaveClass(/bg-green-200/);
  await page.evaluate(() => {
    const el = document.querySelector('[data-row="5"][data-col="0"]') as HTMLElement;
    el.click();
    el.click();
  });
  await expect.poll(() => topPiece(page, 5, 0)).toBe("兵");
  await page.waitForTimeout(1000);
  const moves = log.requests.filter((r) => r.url.endsWith("/move"));
  expect(moves.length).toBe(1);
  expect(log.errors).toEqual([]);
  await expect(page.locator("p.text-red-500")).toHaveCount(0);
});
