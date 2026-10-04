import { test, expect, Page, TestInfo } from "@playwright/test";
import { cell, openModeSelect, press, shot, startAiVsAi, startPvp } from "./helpers";

async function noHorizontalOverflow(page: Page) {
  const { sw, iw } = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth, iw: window.innerWidth,
  }));
  expect(sw, "横スクロールが発生している").toBeLessThanOrEqual(iw);
}

async function boardFullyVisible(page: Page) {
  const iw = await page.evaluate(() => window.innerWidth);
  for (const c of [0, 8]) {
    for (const r of [0, 8]) {
      const b = (await cell(page, r, c).boundingBox())!;
      expect(b.x, `マス(${r},${c})が左に切れている`).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width, `マス(${r},${c})が右に切れている (幅${iw}px)`).toBeLessThanOrEqual(iw + 0.5);
    }
  }
}

async function labelsAligned(page: Page) {
  for (const c of [0, 4, 8]) {
    const lb = (await page.locator(`[data-col-label="${c}"]`).boundingBox())!;
    const cb = (await cell(page, 0, c).boundingBox())!;
    const diff = Math.abs(lb.x + lb.width / 2 - (cb.x + cb.width / 2));
    expect(diff, `列番号${c + 1}がマスとずれている`).toBeLessThanOrEqual(1.5);
  }
}

async function insideViewport(page: Page, selector: string) {
  const vp = await page.evaluate(() => ({ w: window.innerWidth, h: window.innerHeight }));
  const b = (await page.locator(selector).first().boundingBox())!;
  expect(b.x).toBeGreaterThanOrEqual(0);
  expect(b.y).toBeGreaterThanOrEqual(0);
  expect(b.x + b.width).toBeLessThanOrEqual(vp.w + 0.5);
  expect(b.y + b.height).toBeLessThanOrEqual(vp.h + 0.5);
}

async function overlapNote(page: Page, ti: TestInfo, a: string, bSel: string) {
  const ba = await page.locator(a).first().boundingBox();
  const bb = await page.locator(bSel).first().boundingBox();
  if (!ba || !bb) return;
  const overlap = ba.x < bb.x + bb.width && bb.x < ba.x + ba.width && ba.y < bb.y + bb.height && bb.y < ba.y + ba.height;
  if (overlap) ti.annotations.push({ type: "overlap", description: `${a} と ${bSel} が重なっている` });
}

test.describe("F: レイアウト @layout", () => {
  test("F1/F2 メニュー画面", async ({ page }, ti) => {
    await page.goto("/");
    await noHorizontalOverflow(page);
    await shot(page, ti, "01-title");
    await openModeSelect(page, ti);
    await noHorizontalOverflow(page);
    await shot(page, ti, "02-mode");
    await press(page.getByRole("button", { name: /AI同士対戦/ }), ti);
    await noHorizontalOverflow(page);
    await shot(page, ti, "03-aivsai-setup");
    await press(page.getByRole("button", { name: /次へ/ }), ti);
    await noHorizontalOverflow(page);
    await shot(page, ti, "04-rules");
  });

  test("F1/F2 対局画面（PvP）: 盤が切れず列番号がずれない", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await noHorizontalOverflow(page);
    await boardFullyVisible(page);
    await labelsAligned(page);
    await overlapNote(page, ti, "text=← ホーム", "[data-testid=panel-white]");
    if (ti.project.name.startsWith("pc")) {
      const { vh, vw } = await page.evaluate(() => ({ vh: window.innerHeight, vw: window.innerWidth }));
      const b = (await cell(page, 8, 8).boundingBox())!;
      expect(b.y + b.height, "PC で盤の下端が画面外").toBeLessThanOrEqual(vh);
      // 盤が画面の中央に来る（左右のパネルは同じ幅なので盤の中心 ≒ 画面の中心）
      const left = (await cell(page, 4, 0).boundingBox())!;
      const right = (await cell(page, 4, 8).boundingBox())!;
      const center = (left.x + right.x + right.width) / 2;
      expect(Math.abs(center - vw / 2), "PC で盤が中央からずれている").toBeLessThanOrEqual(24);
    }
    await shot(page, ti, "05-game-pvp");
  });

  test("F2 対局画面（AI同士・配置フェーズ）", async ({ page }, ti) => {
    await startAiVsAi(page, "簡単", "簡単", "中級編", ti);
    await expect(page.getByText("初期配置フェーズ")).toBeVisible();
    await noHorizontalOverflow(page);
    await boardFullyVisible(page);
    await overlapNote(page, ti, "text=← ホーム", "text=AI同士対戦 観戦中");
    await shot(page, ti, "06-game-aivsai-setup");
  });

  test("F5 モーダルが画面内に収まる", async ({ page }, ti) => {
    await startPvp(page, "入門編", ti);
    await press(page.getByRole("button", { name: "← ホーム" }), ti);
    await insideViewport(page, "div.rounded-2xl:has-text('タイトルに戻りますか？')");
    await press(page.getByRole("button", { name: "キャンセル" }), ti);
    // 取る/ツケる モーダル
    for (const [fr, fc, tr, tc] of [[6, 4, 5, 4], [2, 4, 3, 4], [5, 4, 4, 4]]) {
      await press(cell(page, fr, fc), ti);
      await press(cell(page, tr, tc), ti);
      await expect(cell(page, fr, fc)).not.toContainText("兵");
    }
    await press(cell(page, 3, 4), ti);
    await press(cell(page, 4, 4), ti);
    await insideViewport(page, "div.rounded-2xl:has-text('どうしますか？')");
    await shot(page, ti, "07-modal-choice");
  });
});
