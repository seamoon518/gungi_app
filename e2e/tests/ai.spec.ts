import { test, expect, Page, TestInfo } from "@playwright/test";
import { cell, cellClass, panel, press, startAi, topPiece, trackApi, waitFor } from "./helpers";

type Log = ReturnType<typeof trackApi>;

/** 人間の手番で、動かせる駒を探して 1 手指す（敵駒への移動は「取る」） */
async function playAnyMove(page: Page, ti: TestInfo, log: Log, me: "black" | "white") {
  const st = log.latest!;
  for (let r = 0; r < 9; r++) {
    for (let c = 0; c < 9; c++) {
      const stack = st.board[r][c].stack;
      if (!stack.length || stack[stack.length - 1].owner !== me) continue;
      await press(cell(page, r, c), ti);
      await page.waitForTimeout(150);
      const target = page.locator("[data-row].bg-green-200").first();
      if ((await target.count()) === 0) continue;
      const before = log.latest!.move_count;
      await press(target, ti);
      const modal = page.getByRole("button", { name: /取る/ });
      if (await modal.isVisible().catch(() => false)) await press(modal, ti);
      await waitFor(() => log.latest!.move_count, (n) => n > before, 15_000);
      return;
    }
  }
  throw new Error("no movable piece");
}

const hasSui = (s: { board: { stack: { type: string; owner: string }[] }[][] }, owner: string) =>
  s.board.some((row) => row.some((c) => c.stack.some((p) => p.type === "帥" && p.owner === owner)));

async function waitHumanTurn(log: Log, me: "black" | "white", timeout = 60_000) {
  await waitFor(() => log.latest, (s) => !!s && (s.game_over || s.current_player === me), timeout);
}

test.describe("D: AIと対戦", () => {
  test("D1 先手: 人間が指すとAIが自動で応手する", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAi(page, "簡単", "先手（黒陣）", "入門編", ti);
    await expect(panel(page, "white")).toContainText("（AI）");
    await press(cell(page, 6, 0), ti);
    await press(cell(page, 5, 0), ti);
    await waitFor(() => log.latest?.move_count ?? 0, (n) => n >= 2, 30_000);
    await expect(panel(page, "black")).toContainText("▶ 手番");
    expect(log.errors).toEqual([]);
  });

  test("D2 後手: AIが先に指し、盤が反転する", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAi(page, "簡単", "後手（白陣）", "入門編", ti);
    const top = (await cell(page, 0, 4).boundingBox())!;
    const bottom = (await cell(page, 8, 4).boundingBox())!;
    expect(top.y).toBeGreaterThan(bottom.y);              // 白陣(自分)が手前
    await waitFor(() => log.latest?.move_count ?? 0, (n) => n >= 1, 30_000);
    await expect(panel(page, "white")).toContainText("▶ 手番");
    // 自分の駒（白）は正しい向き = 盤ごと回転しているので駒自体の rotate と合成される
    await playAnyMove(page, ti, log, "white");
    await waitHumanTurn(log, "white");
    expect(log.errors).toEqual([]);
  });

  test("D1b ランダム: どちらの手番でも開始できる", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAi(page, "簡単", "ランダム", "初級編", ti);
    const ai = log.latest!.ai_player as "black" | "white";
    const me = ai === "black" ? "white" : "black";
    await waitHumanTurn(log, me);
    await playAnyMove(page, ti, log, me);
    await waitHumanTurn(log, me);
    expect(log.errors).toEqual([]);
  });

  test("D3 AIの手番中はAIの駒を動かせない", async ({ page }, ti) => {
    const log = trackApi(page);
    // AI の応答を遅らせて「AIの手番」の時間を確保する
    await page.route("**/ai-move", async (r) => {
      await new Promise((res) => setTimeout(res, 3000));
      await r.continue();
    });
    await startAi(page, "簡単", "先手（黒陣）", "入門編", ti);
    await press(cell(page, 6, 0), ti);
    await press(cell(page, 5, 0), ti);
    await waitFor(() => log.latest?.current_player, (p) => p === "white", 10_000);
    await press(cell(page, 2, 0), ti);            // AI(白)の駒
    await page.waitForTimeout(300);
    expect(await cellClass(page, 2, 0)).not.toContain("bg-yellow-300");
    expect(await page.locator("[data-row].bg-green-200").count()).toBe(0);
    await waitFor(() => log.latest?.current_player, (p) => p === "black", 30_000);
    expect(log.requests.filter((r) => r.url.endsWith("/move")).length).toBe(1);
  });

  test("D3b AIエラー後も人間がAIの駒を動かせない・再試行で再開できる", async ({ page }, ti) => {
    const log = trackApi(page);
    let fail = true;
    await page.route("**/ai-move", (r) => (fail ? r.abort("failed") : r.continue()));
    await startAi(page, "簡単", "先手（黒陣）", "入門編", ti);
    await press(cell(page, 6, 0), ti);
    await press(cell(page, 5, 0), ti);
    await expect(page.getByRole("button", { name: /再試行/ })).toBeVisible({ timeout: 30_000 });
    await press(cell(page, 2, 0), ti);
    await page.waitForTimeout(300);
    expect(await cellClass(page, 2, 0)).not.toContain("bg-yellow-300");
    fail = false;
    await press(page.getByRole("button", { name: /再試行/ }), ti);
    await waitFor(() => log.latest?.current_player, (p) => p === "black", 30_000);
    await expect(page.getByRole("button", { name: /再試行/ })).toHaveCount(0);
  });

  test("D4 待ったでAIの応手ごと戻る", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAi(page, "簡単", "先手（黒陣）", "入門編", ti);
    const initial = JSON.stringify(log.latest!.board);
    await press(cell(page, 6, 0), ti);
    await press(cell(page, 5, 0), ti);
    await waitFor(() => log.latest?.move_count ?? 0, (n) => n >= 2, 30_000);
    await press(panel(page, "black").getByRole("button", { name: "待った" }), ti);
    await press(page.getByRole("dialog").getByRole("button", { name: "待った" }), ti);
    await waitFor(() => log.latest?.move_count, (n) => n === 0, 10_000);
    expect(JSON.stringify(log.latest!.board)).toBe(initial);
    await expect.poll(() => topPiece(page, 6, 0)).toBe("兵");
    await page.waitForTimeout(1500);              // AI が勝手に再行動しない
    expect(log.latest!.move_count).toBe(0);
  });

  test("D5 中級編: AIが配置して対局開始まで進む", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAi(page, "簡単", "先手（黒陣）", "中級編", ti);
    await press(panel(page, "black").getByRole("button", { name: /^帥/ }), ti);
    await press(cell(page, 8, 4), ti);
    await waitFor(() => log.latest, (s) => !!s && s.current_player === "black" && hasSui(s, "white"), 20_000);
    await press(panel(page, "black").getByRole("button", { name: "済を宣言" }), ti);
    await waitFor(() => log.latest?.phase, (p) => p === "play", 60_000);
    await expect(page.getByText("初期配置フェーズ")).toBeHidden();
    await expect(panel(page, "black")).toContainText("▶ 手番");
    expect(log.errors).toEqual([]);
  });

  test("D6 数手進めてもエラーにならない（上級編・普通）", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAi(page, "普通", "先手（黒陣）", "上級編", ti);
    await press(panel(page, "black").getByRole("button", { name: /^帥/ }), ti);
    await press(cell(page, 8, 4), ti);
    await waitFor(() => log.latest, (s) => !!s && s.current_player === "black" && hasSui(s, "white"), 30_000);
    await press(panel(page, "black").getByRole("button", { name: "済を宣言" }), ti);
    await waitFor(() => log.latest?.phase, (p) => p === "play", 90_000);
    for (let i = 0; i < 3; i++) {
      await waitHumanTurn(log, "black");
      if (log.latest!.game_over) break;
      await playAnyMove(page, ti, log, "black");
    }
    expect(log.errors).toEqual([]);
  });
});

test("H9 AI側の手駒は押せる見た目にならない（AIが黒のとき）", async ({ page }, ti) => {
  const log = trackApi(page);
  await startAi(page, "簡単", "後手（白陣）", "入門編", ti);
  await waitFor(() => log.latest?.current_player, (p) => p === "white", 30_000);   // AI(黒)が指し終えた
  const aiHand = panel(page, "black").getByRole("button", { name: /^小/ });
  await expect(aiHand).toHaveClass(/opacity-50/);
  await expect(aiHand).not.toHaveClass(/cursor-pointer/);
  const myHand = panel(page, "white").getByRole("button", { name: /^小/ });
  await expect(myHand).toHaveClass(/cursor-pointer/);
});
