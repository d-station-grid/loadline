import { defineConfig, devices } from "@playwright/test";

// 通しのテスト。Postgres は先に起動しておく（手元は make e2e が docker compose で、CI は service で）。
// Firebase Auth のエミュレータと api（web を同梱）は、ここから起動する
const API_PORT = 8100;
const EMULATOR_HOST = "127.0.0.1:9099";
// demo- で始まるプロジェクトは、エミュレータだけで閉じる（本物の Firebase につながない）
const PROJECT_ID = "demo-loadline";

export const BASE_URL = `http://127.0.0.1:${API_PORT}`;

export default defineConfig({
  testDir: "./tests",
  // テストどうしで DB を分けていないので、1 本ずつ順に流す
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: BASE_URL,
    locale: "en-US",
    timezoneId: "Asia/Tokyo",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `npx firebase emulators:start --only auth --project ${PROJECT_ID}`,
      url: `http://${EMULATOR_HOST}/`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "sh ./serve-api.sh",
      url: `${BASE_URL}/health`,
      reuseExistingServer: false,
      timeout: 180_000,
      env: {
        E2E_API_PORT: String(API_PORT),
        // web のビルドに埋め込む値。Firebase の設定はエミュレータ向けのにせもの
        VITE_FIREBASE_API_KEY: "demo-api-key",
        VITE_FIREBASE_AUTH_DOMAIN: `${PROJECT_ID}.firebaseapp.com`,
        VITE_FIREBASE_PROJECT_ID: PROJECT_ID,
        VITE_FIREBASE_APP_ID: "demo-app-id",
        VITE_FIREBASE_AUTH_EMULATOR_URL: `http://${EMULATOR_HOST}`,
        // 空にすると api と同じオリジンを呼ぶ（本番と同じ）
        VITE_API_URL: "",
        // api。api/.env より環境変数が勝つので、外部サービスの設定はここで空にする。
        // Gemini と Jev がなければ定型の週次レビュー、tts とバケットがなければ声なしになる
        APP_ENV: "e2e",
        DATABASE_URL:
          "postgresql+asyncpg://loadline:loadline@localhost:5432/loadline_e2e",
        FIREBASE_PROJECT_ID: PROJECT_ID,
        // Admin SDK は、これがあるとエミュレータの ID トークンを受け付ける
        FIREBASE_AUTH_EMULATOR_HOST: EMULATOR_HOST,
        CORS_ORIGINS: "[]",
        STATIC_DIR: "../e2e/.web",
        GEMINI_PROJECT: "",
        TYPESAFE_API_KEY: "",
        INTERNAL_AUDIENCE: "",
        INTERNAL_CALLER_EMAIL: "",
        TASKS_QUEUE: "",
        TTS_URL: "",
        GOOGLE_TTS_MODEL: "",
        AUDIO_BUCKET: "",
      },
    },
  ],
});
