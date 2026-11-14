import { expect, test } from "vitest";

import { en, ja } from "./messages";

test("週次レビューを作っている間の秒数は、言語に合わせて書く", () => {
  expect(en.review.elapsed(12)).toBe("12s");
  expect(ja.review.elapsed(12)).toBe("12秒");
});
