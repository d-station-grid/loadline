import type { Expression } from "../../api";

export const EXPRESSIONS: readonly Expression[] = [
  "happy",
  "relaxed",
  "sad",
  "surprised",
];

/** 表情を出す強さ。1 にすると顔が崩れて見えるので、少し控える */
const STRENGTH = 0.8;

/**
 * 今の場面で目指す表情の重み。
 *
 * 話しているあいだは relaxed にする。happy と surprised は口を開けた形まで含む顔全体の
 * モーフで、口パクと重ねると口が閉じなくなる（試作で確認）。sad も口の形を持つので、
 * 合わせて relaxed にそろえる。振り返りの表情は、話す前と話し終えたあとに出す。
 */
export function faceTarget(
  expression: Expression,
  speaking: boolean,
): Record<Expression, number> {
  const shown = speaking ? "relaxed" : expression;
  return {
    happy: shown === "happy" ? STRENGTH : 0,
    relaxed: shown === "relaxed" ? STRENGTH : 0,
    sad: shown === "sad" ? STRENGTH : 0,
    surprised: shown === "surprised" ? STRENGTH : 0,
  };
}

/** 次のまばたきまでの秒数。2〜6 秒のあいだでばらつかせる。random は 0 以上 1 未満 */
export function nextBlinkDelay(random: number): number {
  return 2 + random * 4;
}

/** まばたきの長さ（秒） */
export const BLINK_SECONDS = 0.16;

/**
 * まばたきを始めてからの秒数から、まぶたの閉じ具合（0〜1）を出す。閉じて開くまでを
 * 半周期の sin で表す。終わったら 0
 */
export function blinkWeight(sinceStart: number): number {
  const p = sinceStart / BLINK_SECONDS;
  return p <= 0 || p >= 1 ? 0 : Math.sin(p * Math.PI);
}
