import { expect, Locator, Page, TestInfo } from "@playwright/test";

export type Level = "入門編" | "初級編" | "中級編" | "上級編";
export type Diff = "簡単" | "普通" | "難しい";

export interface GameStateJson {
  game_id: string;
  board: { stack: { type: string; owner: "black" | "white" }[] }[][];
  current_player: "black" | "white";
  hand_pieces: Record<"black" | "white", { type: string; owner: string }[]>;
  game_over: boolean;
  winner: string | null;
  move_count: number;
  phase: "setup" | "play";
  mode: string;
  ai_player: string | null;
}

export const isTouch = (testInfo: TestInfo) => Boolean(testInfo.project.use.hasTouch);

/** タッチ端末ならタップ、PC ならクリック */
export async function press(locator: Locator, testInfo: TestInfo) {
  if (isTouch(testInfo)) await locator.tap();
  else await locator.click();
}

export const cell = (page: Page, r: number, c: number) =>
  page.locator(`[data-row="${r}"][data-col="${c}"]`);

export const panel = (page: Page, player: "black" | "white") =>
  page.getByTestId(`panel-${player}`);

/** バックエンドとの通信を記録する（状態の追跡・リクエスト検査用） */
export function trackApi(page: Page) {
  const log = {
    requests: [] as { method: string; url: string; t: number }[],
    states: [] as GameStateJson[],
    latest: null as GameStateJson | null,
    errors: [] as string[],
  };
  page.on("request", (req) => {
    if (req.url().includes("/game/")) log.requests.push({ method: req.method(), url: req.url(), t: Date.now() });
  });
  page.on("response", async (res) => {
    if (!res.url().includes("/game/")) return;
    if (res.status() >= 400) {
      log.errors.push(`${res.status()} ${res.url()}`);
      return;
    }
    try {
      const body = await res.json();
      if (body && body.game_id && body.board) {
        log.states.push(body);
        log.latest = body;
      }
    } catch {
      /* JSON でないレスポンスは無視 */
    }
  });
  page.on("pageerror", (e) => log.errors.push(`pageerror: ${e.message}`));
  return log;
}

async function chooseLevel(page: Page, level: Level, testInfo: TestInfo) {
  await expect(page.getByText("どのルールで遊びますか？")).toBeVisible();
  await press(page.getByRole("button", { name: new RegExp(level) }), testInfo);
  await expect(page.getByTestId("board")).toBeVisible();
}

export async function openModeSelect(page: Page, testInfo: TestInfo) {
  await page.goto("/");
  await press(page.getByRole("button", { name: "ゲームを始める" }), testInfo);
  await expect(page.getByText("対戦モードを選択してください")).toBeVisible();
}

export async function startPvp(page: Page, level: Level, testInfo: TestInfo) {
  await openModeSelect(page, testInfo);
  await press(page.getByRole("button", { name: /プレイヤー同士で対戦/ }), testInfo);
  await chooseLevel(page, level, testInfo);
}

export async function startAi(
  page: Page, diff: Diff, side: "先手（黒陣）" | "後手（白陣）" | "ランダム", level: Level, testInfo: TestInfo,
) {
  await openModeSelect(page, testInfo);
  await press(page.getByRole("button", { name: /AIと対戦/ }), testInfo);
  await press(page.getByRole("button", { name: diff, exact: true }), testInfo);
  await press(page.getByRole("button", { name: new RegExp(side.replace(/[()（）]/g, ".")) }), testInfo);
  await chooseLevel(page, level, testInfo);
}

export async function startAiVsAi(page: Page, black: Diff, white: Diff, level: Level, testInfo: TestInfo) {
  await openModeSelect(page, testInfo);
  await press(page.getByRole("button", { name: /AI同士対戦/ }), testInfo);
  const blackBox = page.locator("div", { has: page.getByText("黒陣（先手）", { exact: true }) }).last();
  const whiteBox = page.locator("div", { has: page.getByText("白陣（後手）", { exact: true }) }).last();
  await press(blackBox.getByRole("button", { name: new RegExp(`^${black}`) }), testInfo);
  await press(whiteBox.getByRole("button", { name: new RegExp(`^${white}`) }), testInfo);
  await press(page.getByRole("button", { name: /次へ/ }), testInfo);
  await chooseLevel(page, level, testInfo);
}

/** 盤上のマスの最上段の駒（文字）を返す */
export async function topPiece(page: Page, r: number, c: number): Promise<string> {
  // locator.textContent は要素が現れるまで待ち続けるため、DOM を 1 回で読む（空きマスは ""）
  return page.evaluate(([row, col]) => {
    const el = document.querySelector(`[data-row="${row}"][data-col="${col}"] span`);
    return el?.textContent?.trim() ?? "";
  }, [r, c] as const);
}

/** 背景色クラスでハイライト状態を判定 */
export async function cellClass(page: Page, r: number, c: number) {
  return (await cell(page, r, c).getAttribute("class")) ?? "";
}

export async function waitFor<T>(fn: () => T | Promise<T>, pred: (v: T) => boolean, timeoutMs: number, stepMs = 200) {
  const end = Date.now() + timeoutMs;
  let v = await fn();
  while (!pred(v)) {
    if (Date.now() > end) throw new Error(`waitFor timeout (last=${JSON.stringify(v)?.slice(0, 200)})`);
    await new Promise((r) => setTimeout(r, stepMs));
    v = await fn();
  }
  return v;
}

/** CDP で指を置いたまま待つ（長押し） */
export async function longPress(page: Page, locator: Locator, ms = 700) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("no bounding box");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  await page.waitForTimeout(ms);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await cdp.detach();
}

export async function shot(page: Page, testInfo: TestInfo, name: string) {
  await page.screenshot({ path: `screenshots/${testInfo.project.name}/${name}.png`, fullPage: true });
}
