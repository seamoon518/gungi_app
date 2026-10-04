import { defineConfig, devices } from "@playwright/test";

/**
 * E2E テスト設定
 *  - E2E_BASE_URL を指定すると既存のサイト（デプロイ済み環境など）に対して実行する。
 *    未指定時はローカルで backend(:8002) と frontend(:3000) を起動する。
 *  - @layout タグのテストは全画面サイズ、それ以外は PC/スマホ代表サイズで実行する。
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const local = !process.env.E2E_BASE_URL;

const chromium = { browserName: "chromium" as const };
const representative = /pc-1366|sp-390/;

export default defineConfig({
  testDir: "./tests",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  workers: process.env.E2E_WORKERS ? Number(process.env.E2E_WORKERS) : 2,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "pc-1366", use: { ...chromium, viewport: { width: 1366, height: 768 } } },
    { name: "pc-1920", use: { ...chromium, viewport: { width: 1920, height: 1080 } } },
    { name: "sp-320", use: { ...devices["iPhone SE"], ...chromium } },
    { name: "sp-375", use: { ...devices["iPhone SE (3rd gen)"], ...chromium } },
    { name: "sp-390", use: { ...devices["iPhone 13"], ...chromium } },
    { name: "sp-412", use: { ...devices["Pixel 7"], ...chromium } },
  ].map((p) => ({
    ...p,
    // 機能テストは代表サイズのみ、レイアウトテストは全サイズ
    grep: representative.test(p.name) ? undefined : /@layout/,
  })),
  webServer: local
    ? [
        {
          command: "python3 -m uvicorn main:app --port 8002",
          cwd: "../backend",
          url: "http://localhost:8002/",
          reuseExistingServer: true,
          timeout: 60_000,
        },
        {
          command: "npm run build && npx next start -p 3000",
          cwd: "../frontend",
          url: "http://localhost:3000",
          reuseExistingServer: true,
          timeout: 300_000,
        },
      ]
    : undefined,
});
