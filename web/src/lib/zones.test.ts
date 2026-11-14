import { expect, test } from "vitest";

import { boundariesForMax, suggestBoundaries } from "./zones";

test("最大心拍の 80% と 90% を、整数に丸めて出す", () => {
  expect(suggestBoundaries(176)).toEqual({ low: 141, high: 158 });
  expect(suggestBoundaries(185)).toEqual({ low: 148, high: 167 });
});

test("範囲の端の最大心拍でも、境目は低・中・高の順に並び、最大心拍より低い", () => {
  for (const max of [100, 250]) {
    const b = suggestBoundaries(max);
    expect(b).not.toBeNull();
    expect(60 <= b!.low && b!.low < b!.high && b!.high < max).toBe(true);
  }
});

test("最大心拍が空、範囲の外、整数でなければ出さない", () => {
  for (const max of [null, 99, 251, 17, 176.5]) {
    expect(suggestBoundaries(max)).toBeNull();
  }
});

test("境目が空なら入れ、出した値のままなら出し直す", () => {
  const empty = { low: null, high: null };
  expect(boundariesForMax(176, empty, false)).toEqual({
    boundaries: { low: 141, high: 158 },
    filled: true,
  });
  expect(boundariesForMax(180, { low: 141, high: 158 }, true)).toEqual({
    boundaries: { low: 144, high: 162 },
    filled: true,
  });
});

test("自分で入れた境目と、入力の途中の最大心拍では変えない", () => {
  const mine = { low: 135, high: 160 };
  expect(boundariesForMax(180, mine, false)).toEqual({
    boundaries: mine,
    filled: false,
  });
  expect(boundariesForMax(18, { low: 141, high: 158 }, true)).toEqual({
    boundaries: { low: 141, high: 158 },
    filled: true,
  });
});
