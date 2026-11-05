import { expect, test } from "vitest";

import { formatDay, formatDuration } from "./format";

test("時間は時と分で出す", () => {
  expect(formatDuration(4028)).toBe("1h 07m");
  expect(formatDuration(1500)).toBe("25m");
  expect(formatDuration(0)).toBe("0m");
});

test("0 より長く 30 秒未満の時間は、0m ではなく <1m にする", () => {
  expect(formatDuration(29)).toBe("<1m");
  expect(formatDuration(1)).toBe("<1m");
});

test("日付だけの値は、タイムゾーンで前の日にずらさない", () => {
  expect(formatDay("2026-10-26")).toMatch(/26/);
});
