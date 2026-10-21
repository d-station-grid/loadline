// メモのラベルの長さ。チャートの吹き出しに収まるよう、文字数ではなく幅で数える。
// api の app/domain/label.py と同じ数え方にしてある。変えるときは両方を直す。

import { WIDE_RANGES } from "./label-widths.gen";

/** 半角なら 12 文字、全角なら 6 文字 */
export const MAX_LABEL_WIDTH = 12;

/** 範囲は api の Unicode の表から生成したもの。小さい順に並んでいるので二分探索で探す */
function isWide(codePoint: number): boolean {
  let lo = 0;
  let hi = WIDE_RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const [from, to] = WIDE_RANGES[mid];
    if (codePoint < from) hi = mid - 1;
    else if (codePoint > to) lo = mid + 1;
    else return true;
  }
  return false;
}

/** 全角と幅広を 2、それ以外を 1 として数える。「①」「α」のように環境で幅が変わる文字は 1 */
export function displayWidth(text: string): number {
  let width = 0;
  for (const ch of text) {
    width += isWide(ch.codePointAt(0) ?? 0) ? 2 : 1;
  }
  return width;
}

/** 送る形に整える。前後の空白を落とし、空ならラベルなし（null）。api と同じ */
export function normalizeLabel(text: string): string | null {
  const trimmed = text.trim();
  return trimmed === "" ? null : trimmed;
}
