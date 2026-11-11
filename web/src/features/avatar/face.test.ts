import { expect, test } from "vitest";

import { blinkWeight, BLINK_SECONDS, faceTarget, nextBlinkDelay } from "./face";

test("話していないときは、振り返りの表情だけを出す", () => {
  expect(faceTarget("happy", false)).toEqual({
    happy: 0.8,
    relaxed: 0,
    sad: 0,
    surprised: 0,
  });
  expect(faceTarget("sad", false).sad).toBe(0.8);
});

test("話しているあいだは、どの表情でも relaxed にする（口パクと重ねると口が閉じないため）", () => {
  for (const e of ["happy", "relaxed", "sad", "surprised"] as const) {
    expect(faceTarget(e, true)).toEqual({
      happy: 0,
      relaxed: 0.8,
      sad: 0,
      surprised: 0,
    });
  }
});

test("まばたきは 2〜6 秒おき", () => {
  expect(nextBlinkDelay(0)).toBe(2);
  expect(nextBlinkDelay(0.5)).toBe(4);
  expect(nextBlinkDelay(0.999)).toBeLessThan(6);
});

test("まぶたは途中で閉じきり、始めと終わりは開いている", () => {
  expect(blinkWeight(0)).toBe(0);
  expect(blinkWeight(BLINK_SECONDS / 2)).toBeCloseTo(1);
  expect(blinkWeight(BLINK_SECONDS)).toBe(0);
  expect(blinkWeight(BLINK_SECONDS * 2)).toBe(0);
  expect(blinkWeight(-0.1)).toBe(0);
});
