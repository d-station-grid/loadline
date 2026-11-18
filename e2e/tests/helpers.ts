import { expect, type Page } from "@playwright/test";

/**
 * Google でログインする。エミュレータでは本物の Google ではなく、アカウントを作るだけの
 * 画面がポップアップで開く。毎回新しいメールアドレスで、まっさらな利用者として入る
 */
export async function signInAsNewUser(page: Page): Promise<string> {
  const email = `runner-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/");
  const popupOpened = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Sign in with Google" }).click();
  const popup = await popupOpened;
  await popup.getByRole("button", { name: "Add new account" }).click();
  await popup.locator("#email-input").fill(email);
  await popup.getByRole("button", { name: "Sign in with Google.com" }).click();

  // まだ記録が届いていないので、導入の案内が出る。ここでは飛ばす
  await page.getByRole("button", { name: "Skip for now" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  return email;
}

/** 設定の画面で最大心拍と安静時心拍を保存する。ゾーンの境目は最大心拍から埋まる */
export async function saveHeartRate(page: Page): Promise<void> {
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Settings" })
    .click();
  const settings = page.getByRole("region", { name: "Settings" });
  await settings
    .getByRole("spinbutton", { name: "Max heart rate" })
    .fill("185");
  await settings
    .getByRole("spinbutton", { name: "Resting heart rate" })
    .fill("50");
  await settings.getByRole("button", { name: "Save" }).click();
  await expect(settings.getByText("Saved")).toBeVisible();
}

/** "2026-11-17 07:00:00 +0900" の形。Health Auto Export が送る日時の書き方 */
function hae(date: Date): string {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${jst.getUTCFullYear()}-${p(jst.getUTCMonth() + 1)}-${p(jst.getUTCDate())} ` +
    `${p(jst.getUTCHours())}:${p(jst.getUTCMinutes())}:${p(jst.getUTCSeconds())} +0900`
  );
}

/**
 * Health Auto Export が送る形の記録。Apple Watch のラン 1 本を、前日の朝に 30 分。
 * 期間で切る画面に出るよう、日付はテストを流した日から決める
 */
export function workoutPayload(): unknown {
  // 日本時間の前日の朝 7 時（UTC では 9 時間前）
  const today = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const start = new Date(
    Date.UTC(
      today.getUTCFullYear(),
      today.getUTCMonth(),
      today.getUTCDate() - 1,
      7 - 9,
    ),
  );
  const minutes = 30;
  const end = new Date(start.getTime() + minutes * 60 * 1000);
  const heartRateData = Array.from({ length: minutes }, (_, i) => ({
    date: hae(new Date(start.getTime() + i * 60 * 1000)),
    Min: 135,
    Avg: 140,
    Max: 145,
    units: "count/min",
  }));
  return {
    data: {
      workouts: [
        {
          id: `e2e-${start.getTime()}`,
          name: "Outdoor Run",
          start: hae(start),
          end: hae(end),
          duration: minutes * 60,
          source: { name: "Apple Watch" },
          avgHeartRate: { qty: 140, units: "count/min" },
          maxHeartRate: { qty: 145, units: "count/min" },
          heartRateData,
        },
      ],
    },
  };
}
