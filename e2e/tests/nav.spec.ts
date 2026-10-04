import { test, expect } from "@playwright/test";
import { openModeSelect, press, startPvp, trackApi } from "./helpers";

test.describe("B: 画面遷移", () => {
  test("B1 各画面の遷移と「戻る」", async ({ page }, ti) => {
    await openModeSelect(page, ti);

    // PvP → ルール選択 → 戻る
    await press(page.getByRole("button", { name: /プレイヤー同士で対戦/ }), ti);
    await expect(page.getByText("どのルールで遊びますか？")).toBeVisible();
    await press(page.getByRole("button", { name: "← 戻る" }), ti);
    await expect(page.getByText("対戦モードを選択してください")).toBeVisible();

    // AI → 難易度 → 先後 → ルール → 戻る ×3
    await press(page.getByRole("button", { name: /AIと対戦/ }), ti);
    await expect(page.getByText("誰と対戦しますか？")).toBeVisible();
    await press(page.getByRole("button", { name: "普通", exact: true }), ti);
    await expect(page.getByText("先手・後手を選んでください")).toBeVisible();
    await press(page.getByRole("button", { name: /後手（白陣）/ }), ti);
    await expect(page.getByText("どのルールで遊びますか？")).toBeVisible();
    await press(page.getByRole("button", { name: "← 戻る" }), ti);
    await expect(page.getByText("先手・後手を選んでください")).toBeVisible();
    await press(page.getByRole("button", { name: "← 戻る" }), ti);
    await expect(page.getByText("誰と対戦しますか？")).toBeVisible();
    await press(page.getByRole("button", { name: "← 戻る" }), ti);

    // AI同士 → 強さ → ルール → 戻る ×2
    await press(page.getByRole("button", { name: /AI同士対戦/ }), ti);
    await expect(page.getByText("AI同士の強さを設定してください")).toBeVisible();
    await press(page.getByRole("button", { name: /次へ/ }), ti);
    await expect(page.getByText("どのルールで遊びますか？")).toBeVisible();
    await press(page.getByRole("button", { name: "← 戻る" }), ti);
    await expect(page.getByText("AI同士の強さを設定してください")).toBeVisible();
    await press(page.getByRole("button", { name: "← 戻る" }), ti);
    await expect(page.getByText("対戦モードを選択してください")).toBeVisible();
  });

  test("B2 ホームボタンと確認モーダル", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await press(page.getByRole("button", { name: "← ホーム" }), ti);
    await expect(page.getByText("タイトルに戻りますか？")).toBeVisible();
    await expect(page.getByText("対局が中断されます")).toBeVisible();
    await press(page.getByRole("button", { name: "キャンセル" }), ti);
    await expect(page.getByText("タイトルに戻りますか？")).toBeHidden();
    await expect(page.getByTestId("board")).toBeVisible();
    await press(page.getByRole("button", { name: "← ホーム" }), ti);
    await press(page.getByRole("button", { name: "戻る", exact: true }), ti);
    await expect(page.getByRole("button", { name: "ゲームを始める" })).toBeVisible();
  });

  test("B3 バックエンドに繋がらないときエラー表示され操作を続けられる", async ({ page }, ti) => {
    const log = trackApi(page);
    await page.route("**/game/new", (r) => r.abort("connectionrefused"));
    await openModeSelect(page, ti);
    await press(page.getByRole("button", { name: /プレイヤー同士で対戦/ }), ti);
    await press(page.getByRole("button", { name: /入門編/ }), ti);
    await expect(page.locator("main p.text-red-500")).toBeVisible();
    // ボタンが再び押せる（固まらない）
    await expect(page.getByRole("button", { name: /入門編/ })).toBeEnabled();
    await page.unroute("**/game/new");
    await press(page.getByRole("button", { name: /入門編/ }), ti);
    await expect(page.getByTestId("board")).toBeVisible();
    expect(log.errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
  });
});
