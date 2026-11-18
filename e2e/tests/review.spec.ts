import { expect, test } from "@playwright/test";

import { saveHeartRate, signInAsNewUser } from "./helpers";

// 週次レビューの選択肢を選ぶと保存され、開き直しても残っている
test("a user's chosen option is saved and still chosen after reopening", async ({
  page,
}) => {
  await signInAsNewUser(page);
  // 週次レビューを作るには心拍の設定が要る
  await saveHeartRate(page);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Dashboard" })
    .click();

  // Gemini を呼ばないので、定型の週次レビューができる
  const review = page.getByRole("region", { name: "This week's review" });
  await review
    .getByRole("button", { name: "Create this week's review" })
    .click();
  const options = review
    .getByRole("group", { name: "How will you spend the week ahead?" })
    .getByRole("button");
  await expect(options.first()).toBeEnabled();
  const count = await options.count();
  expect(count).toBeGreaterThan(1);

  const chosen = options.first();
  const label = (await chosen.locator("strong").textContent()) ?? "";
  await chosen.click();
  await expect(chosen).toHaveAttribute("aria-pressed", "true");

  // 開き直す。記録はまだ届いていないので、導入の案内を飛ばしてダッシュボードへ
  await page.reload();
  await page.getByRole("button", { name: "Skip for now" }).click();
  const again = page
    .getByRole("region", { name: "This week's review" })
    .getByRole("group", { name: "How will you spend the week ahead?" })
    .getByRole("button", { pressed: true });
  await expect(again).toHaveCount(1);
  await expect(again.locator("strong")).toHaveText(`✓ ${label}`);
});
