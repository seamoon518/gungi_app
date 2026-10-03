import { test, expect } from "@playwright/test";
import {
  cell, isTouch, longPress, panel, press, startAiVsAi, startPvp, trackApi, waitFor, Level,
} from "./helpers";

const playMoves = (log: ReturnType<typeof trackApi>) =>
  log.latest && log.latest.phase === "play" ? log.latest.move_count : -1;

test.describe("E: AI同士（観戦）", () => {
  for (const level of ["入門編", "初級編", "中級編", "上級編"] as Level[]) {
    test(`E1/E2 ${level}: 配置から対局まで止まらずに進む`, async ({ page }, ti) => {
      const log = trackApi(page);
      await startAiVsAi(page, "簡単", "簡単", level, ti);
      await expect(page.getByText("AI同士対戦 観戦中")).toBeVisible();
      const start = log.latest!.move_count;
      await waitFor(() => playMoves(log), (n) => n >= start + 6 || !!log.latest?.game_over, 150_000);
      expect(log.errors).toEqual([]);
      await expect(page.locator("p.text-red-500")).toHaveCount(0);
      // 観戦中は盤をクリックしても駒を動かせない
      const movesBefore = log.requests.filter((r) => r.url.endsWith("/move")).length;
      await press(cell(page, 6, 4), ti);
      await press(cell(page, 5, 4), ti);
      expect(log.requests.filter((r) => r.url.endsWith("/move")).length).toBe(movesBefore);
    });
  }

  test("E3 観戦中も凝モードとスタック確認が維持される", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAiVsAi(page, "簡単", "簡単", "入門編", ti);
    await waitFor(() => log.latest!.move_count, (n) => n >= 1, 30_000);
    await press(panel(page, "black").getByRole("button", { name: "凝" }), ti);
    await expect(panel(page, "black").getByRole("button", { name: "凝 ON" })).toBeVisible();
    const n0 = log.latest!.move_count;
    await waitFor(() => log.latest!.move_count, (n) => n >= n0 + 2, 30_000);
    await expect(panel(page, "black").getByRole("button", { name: "凝 ON" })).toBeVisible();

    // 凝モードでタップ（PC はクリック）するとスタックを確認できる
    await press(cell(page, 8, 4), ti);
    await expect(page.getByText("スタック確認")).toBeVisible();
    const n1 = log.latest!.move_count;
    await waitFor(() => log.latest!.move_count, (n) => n >= n1 + 1, 30_000);
    await expect(page.getByText("スタック確認")).toBeVisible();  // AI が指しても閉じない
    await press(page.getByRole("button", { name: "閉じる" }), ti);

    if (isTouch(ti)) {
      await press(panel(page, "black").getByRole("button", { name: "凝 ON" }), ti);
      await longPress(page, cell(page, 8, 4));
      await expect(page.getByText("スタック確認")).toBeVisible();
      const n2 = log.latest!.move_count;
      await waitFor(() => log.latest!.move_count, (n) => n >= n2 + 1, 30_000);
      await expect(page.getByText("スタック確認")).toBeVisible();
    }
  });

  test("E4 観戦中にホームへ戻って別の対局を始めても前の対局が混ざらない", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAiVsAi(page, "簡単", "簡単", "入門編", ti);
    const oldId = log.latest!.game_id;
    await waitFor(() => log.latest!.move_count, (n) => n >= 1, 30_000);
    // AI の思考中（リクエスト送信直後）にホームへ戻る
    await page.waitForRequest((r) => r.url().endsWith(`${oldId}/ai-move`));
    await press(page.getByRole("button", { name: "← ホーム" }), ti);
    await press(page.getByRole("button", { name: "戻る", exact: true }), ti);
    await expect(page.getByRole("button", { name: "ゲームを始める" })).toBeVisible();
    const leftAt = Date.now();
    await page.waitForTimeout(4000);
    const oldAfterLeave = log.requests.filter((r) => r.url.includes(oldId) && r.t > leftAt + 500);
    expect(oldAfterLeave, "タイトル画面で前の対局のAIが動き続けている").toEqual([]);

    // 別の対局（中級編）を開始
    await startAiVsAi(page, "簡単", "普通", "中級編", ti);
    const newId = log.latest!.game_id;
    expect(newId).not.toBe(oldId);
    const startedAt = Date.now();
    await page.waitForTimeout(6000);
    const stray = log.requests.filter((r) => r.t > startedAt && !r.url.includes(newId));
    expect(stray, "新しい対局中に前の対局へのリクエストがある").toEqual([]);
    const shownIds = new Set(log.states.filter((s) => log.states.indexOf(s) >= 0).map((s) => s.game_id));
    expect(log.latest!.game_id).toBe(newId);
    await expect(page.getByText("初期配置フェーズ")).toBeVisible();
    expect(shownIds.has(newId)).toBe(true);
  });

  test("E5 通信エラーが起きても自動で再開する", async ({ page }, ti) => {
    const log = trackApi(page);
    let failures = 0;
    await page.route("**/ai-move", (r) => {
      if (failures < 1) {
        failures++;
        return r.abort("failed");
      }
      return r.continue();
    });
    await startAiVsAi(page, "簡単", "簡単", "入門編", ti);
    await waitFor(() => log.latest!.move_count, (n) => n >= 3, 60_000);
    expect(failures).toBe(1);
  });

  test("E5b 通信エラーが続くと再試行ボタンが出て、押すと再開する", async ({ page }, ti) => {
    const log = trackApi(page);
    let fail = true;
    await page.route("**/ai-move", (r) => (fail ? r.abort("failed") : r.continue()));
    await startAiVsAi(page, "簡単", "簡単", "入門編", ti);
    await expect(page.getByRole("button", { name: /再試行/ })).toBeVisible({ timeout: 30_000 });
    fail = false;
    await press(page.getByRole("button", { name: /再試行/ }), ti);
    await waitFor(() => log.latest!.move_count, (n) => n >= 2, 60_000);
  });

  test("E6 バナーに難易度が日本語で表示される", async ({ page }, ti) => {
    await startAiVsAi(page, "簡単", "難しい", "入門編", ti);
    const banner = page.getByText("AI同士対戦 観戦中");
    await expect(banner).toContainText("黒: 簡単");
    await expect(banner).toContainText("白: 難しい");
  });
});

test.describe("復帰: 再読み込みしても対局が続く", () => {
  test("R1 PvP: 再読み込み後に同じ盤面で再開", async ({ page }, ti) => {
    const log = trackApi(page);
    await startPvp(page, "入門編", ti);
    await press(cell(page, 6, 0), ti);
    await press(cell(page, 5, 0), ti);
    await waitFor(() => log.latest!.move_count, (n) => n === 1, 10_000);
    await page.reload();
    await expect(page.getByTestId("board")).toBeVisible();
    await expect(cell(page, 5, 0)).toContainText("兵");
    await expect(panel(page, "white")).toContainText("▶ 手番");
  });

  test("R2 AI同士: 再読み込み後も観戦が続く", async ({ page }, ti) => {
    const log = trackApi(page);
    await startAiVsAi(page, "簡単", "簡単", "入門編", ti);
    await waitFor(() => log.latest!.move_count, (n) => n >= 1, 30_000);
    await page.reload();
    const id = log.latest!.game_id;
    await expect(page.getByTestId("board")).toBeVisible();
    const n0 = log.latest!.move_count;
    await waitFor(() => log.latest!.move_count, (n) => n >= n0 + 2, 30_000);
    expect(log.latest!.game_id).toBe(id);
  });

  test("R3 サーバー側で対局が消えていたらタイトルに戻りメッセージを出す", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await page.route("**/state", (r) => r.fulfill({ status: 404, json: { detail: "Game not found." } }));
    await page.reload();
    await expect(page.getByRole("button", { name: "ゲームを始める" })).toBeVisible();
    await expect(page.getByText(/対局データが見つかりません/)).toBeVisible();
  });
});

test("E7 AI同士の手数上限で引き分けになったことが表示される", async ({ page }, ti) => {
  // 300 手を実際に指すと時間がかかるため、終局状態を返す API をモックして表示だけ確認する
  await page.route("**/game/new", async (r) => {
    const res = await r.fetch();
    const st = await res.json();
    await r.fulfill({ json: { ...st, game_over: true, winner: null, end_reason: "move_limit", move_count: 300 } });
  });
  await startAiVsAi(page, "簡単", "簡単", "入門編", ti);
  await expect(page.getByText("ゲーム終了")).toBeVisible();
  await expect(page.getByText("手数上限（300手）に達したため引き分け")).toBeVisible();
});
