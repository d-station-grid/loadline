import { expect, test } from "@playwright/test";

import { saveHeartRate, signInAsNewUser, workoutPayload } from "./helpers";

// 登録して、設定し、iPhone から記録が届くと画面に出るまで
test("a new user saves settings, issues a token, and sees the workouts it sends", async ({
  page,
  request,
}) => {
  await signInAsNewUser(page);
  await saveHeartRate(page);

  // トークンは発行したときに 1 回だけ見える
  const connection = page.getByRole("region", { name: "iPhone connection" });
  await connection.getByRole("button", { name: "Issue token" }).click();
  const token = await connection
    .getByRole("definition")
    .filter({ hasText: "Your new token" })
    .locator("code")
    .textContent();
  expect(token).toBeTruthy();

  // iPhone の Health Auto Export の代わりに、同じ形の記録を送る
  const response = await request.post("/ingest", {
    headers: { Authorization: `Bearer ${token}` },
    data: workoutPayload(),
  });
  expect(response.ok()).toBe(true);
  expect(await response.json()).toMatchObject({ workouts_added: 1 });

  // 開き直すと、記録が届いたのでダッシュボードから始まる
  await page.reload();
  const recent = page.getByRole("region", { name: "Recent workouts" });
  // 平均心拍は、送った心拍（平均 140）がそのまま出る
  const row = recent.getByRole("row").filter({ hasText: "Run" });
  await expect(row.getByRole("cell", { name: "Run" })).toBeVisible();
  await expect(
    row.getByRole("cell", { name: "140", exact: true }),
  ).toBeVisible();
  const chart = page.getByRole("region", {
    name: "Fitness, fatigue and VO2max",
  });
  await expect(chart.locator("canvas").first()).toBeVisible();

  // 一覧にも出る
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Workouts" })
    .click();
  await expect(
    page.getByRole("main").getByRole("cell", { name: "Run" }).first(),
  ).toBeVisible();
});
