import { expect, test } from "vitest";

import {
  blinkWeight,
  BLINK_SECONDS,
  faceEasing,
  faceTarget,
  nextBlinkDelay,
  nextMouth,
} from "./face";

test("話していないときは、週次レビューの表情だけを出す", () => {
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

test("表情の寄せ方は、画面の書き換えの回数によらない", () => {
  // 0.5 秒で詰める差を、30Hz・60Hz・120Hz で比べる
  function remaining(hz: number) {
    let left = 1;
    for (let i = 0; i < hz / 2; i++) left *= 1 - faceEasing(1 / hz);
    return left;
  }
  expect(remaining(30)).toBeCloseTo(remaining(60), 10);
  expect(remaining(120)).toBeCloseTo(remaining(60), 10);
  // 60Hz では、試作と同じく 1 フレームに約 8% 寄せる
  expect(faceEasing(1 / 60)).toBeCloseTo(0.08, 2);
  expect(faceEasing(0)).toBe(0);
});

test("口は声へ寄せる。開くのは速く、閉じるのはゆっくり", () => {
  const opened = nextMouth(0, 1, 1 / 60);
  const closed = nextMouth(1, 0, 1 / 60);
  // 60Hz の 1 フレームで、開くときは約半分、閉じるときは約 4 分の 1 詰める
  expect(opened).toBeCloseTo(0.5, 1);
  expect(1 - closed).toBeCloseTo(0.25, 1);
  // 画面の書き換えの回数によらない
  let at30 = 0;
  let at120 = 0;
  for (let i = 0; i < 3; i++) at30 = nextMouth(at30, 1, 1 / 30);
  for (let i = 0; i < 12; i++) at120 = nextMouth(at120, 1, 1 / 120);
  expect(at30).toBeCloseTo(at120, 10);
  expect(nextMouth(0.3, 0.3, 1 / 60)).toBe(0.3);
});
