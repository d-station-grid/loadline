import { expect, test } from "vitest";

import { displayWidth, MAX_LABEL_WIDTH, normalizeLabel } from "./label";

// api の tests/test_domain_label.py と同じ例。数え方がずれないように
test.each([
  ["Race", 4],
  ["大会", 4],
  ["5km走", 5],
  ["ｱｲｳ", 3], // 半角カタカナは 1
  ["ＡＢ", 4], // 全角英数字は 2
  ["😷", 2],
  ["①α", 2], // 環境で幅が変わる文字は 1
  ["", 0],
])("%s の幅は %i", (text, width) => {
  expect(displayWidth(text)).toBe(width);
});

test("半角 12 文字、全角 6 文字でちょうど上限", () => {
  expect(displayWidth("x".repeat(12))).toBe(MAX_LABEL_WIDTH);
  expect(displayWidth("あ".repeat(6))).toBe(MAX_LABEL_WIDTH);
});

test("前後の空白を落とし、空ならラベルなし", () => {
  expect(normalizeLabel("  Race ")).toBe("Race");
  expect(normalizeLabel("   ")).toBeNull();
});
