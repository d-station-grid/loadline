import { expect, test } from "vitest";

import { ja } from "../i18n/messages";
import { dayInZone, formatDay, formatDuration, nextDay } from "./format";

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

test("時刻を、そのタイムゾーンの日付にする", () => {
  // 東京の 11/1 の朝 6 時は、UTC ではまだ 10/31
  expect(dayInZone("2026-10-31T21:00:00Z", "Asia/Tokyo")).toBe("2026-11-01");
  expect(dayInZone("2026-10-31T21:00:00Z", "UTC")).toBe("2026-10-31");
});

test("次の日は、月と年をまたいでも数える", () => {
  expect(nextDay("2026-10-31")).toBe("2026-11-01");
  expect(nextDay("2026-12-31")).toBe("2027-01-01");
});

test("日本語の時間の書き方", () => {
  expect(formatDuration(4028, ja.duration)).toBe("1時間07分");
  expect(formatDuration(1500, ja.duration)).toBe("25分");
  expect(formatDuration(10, ja.duration)).toBe("1分未満");
});

test("日付は画面の言語のロケールで書く", () => {
  expect(formatDay("2026-10-26", "en-US")).toBe("Oct 26");
  expect(formatDay("2026-10-26", "ja-JP")).toBe("10月26日");
});
