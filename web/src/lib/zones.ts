/**
 * 最大心拍から、強度の境目 2 つの初期値を出す。設定の画面で、境目が空のときに入れておく。
 *
 * 低・中の境目（LT1 付近）は最大心拍の 80%、中・高の境目（LT2 付近）は 90%。
 * 市民ランナーの LT1 は平均で最大心拍の 79〜84%（Nuuttila ら 2025, Eur J Appl Physiol
 * 125:2161–2171）、VT1 は 81±2%・VT2 は 91±2%（Seiler & Kjerland 2006, Scand J Med Sci
 * Sports 16:49–56）。個人差が ±15 拍ほどあるので、狙いをつけるための値で、利用者が直せる。
 * 年齢からの推定式（220 − 年齢）は使わない。
 */

export const LOW_MID_FRACTION = 0.8;
export const MID_HIGH_FRACTION = 0.9;

/** 最大心拍として受け付ける範囲。api の schemas/settings.py と同じ */
const MAX_HEART_RATE_MIN = 100;
const MAX_HEART_RATE_MAX = 250;

export type Boundaries = { low: number | null; high: number | null };

/** 最大心拍から出した境目。最大心拍が範囲の外か整数でなければ null（入力の途中など） */
export function suggestBoundaries(
  maxHeartRate: number | null,
): { low: number; high: number } | null {
  if (
    maxHeartRate == null ||
    !Number.isInteger(maxHeartRate) ||
    maxHeartRate < MAX_HEART_RATE_MIN ||
    maxHeartRate > MAX_HEART_RATE_MAX
  ) {
    return null;
  }
  return {
    low: Math.round(maxHeartRate * LOW_MID_FRACTION),
    high: Math.round(maxHeartRate * MID_HIGH_FRACTION),
  };
}

/**
 * 最大心拍を変えたときの境目と、それが最大心拍から出した値か。
 *
 * 境目が 2 つとも空か、最大心拍から出した値のまま（filled）なら、新しい最大心拍から出し
 * 直す。片方だけ空なら、空いている方だけを埋める（入っている方は利用者の値なので変えない）。
 * 利用者が自分で入れた境目は変えない。最大心拍が入力の途中（範囲の外）なら何もしない。
 *
 * 心拍の 4 つは保存に必須なので、境目を空のまま残さないために埋める。埋めた値が
 * 入っている方と前後していれば、保存の前の検査で知らせる。
 */
export function boundariesForMax(
  maxHeartRate: number | null,
  current: Boundaries,
  filled: boolean,
): { boundaries: Boundaries; filled: boolean } {
  const next = suggestBoundaries(maxHeartRate);
  if (next === null) return { boundaries: current, filled };
  if (filled || (current.low == null && current.high == null)) {
    return { boundaries: next, filled: true };
  }
  return {
    boundaries: {
      low: current.low ?? next.low,
      high: current.high ?? next.high,
    },
    filled: false,
  };
}
