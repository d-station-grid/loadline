import { expect, test } from "@playwright/test";

// 登録なしで一通り見られること。デモデータは serve-api.sh が seed_demo で入れる
test("a guest sees the demo chart, the review and options they can't press", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Try as a guest" }).click();

  await expect(
    page.getByText("Viewing demo data as a guest (read-only)"),
  ).toBeVisible();

  // チャートは ECharts が canvas に描く
  const chart = page.getByRole("region", {
    name: "Fitness, fatigue and VO2max",
  });
  await expect(chart.locator("canvas").first()).toBeVisible();

  // 週次レビューの字幕と選択肢。デモの最後の週は、選択肢を選ばずに残してある
  const review = page.getByRole("region", { name: "This week's review" });
  // 字幕の中身は定型（Gemini を呼ばない）。文があることだけを見る
  await expect(review.locator(".review-script")).not.toBeEmpty();
  const options = review.getByRole("group", {
    name: "How will you spend the week ahead?",
  });
  const buttons = options.getByRole("button");
  await expect(buttons).toHaveCount(3);
  for (const button of await buttons.all()) {
    await expect(button).toBeDisabled();
  }
  await expect(
    review.getByText(
      "Guests can't choose an option. Sign in to plan your week.",
    ),
  ).toBeVisible();
});
