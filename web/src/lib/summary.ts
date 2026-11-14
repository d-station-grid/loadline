// ダッシュボードの数字の書き方。比べる計算は api がしているので、ここでは書き方だけを決める。

/** 期間の選択肢。週の数を api に渡す。名前と「直近 3 か月」などの言い方は辞書（ranges） */
export const RANGES = [
  { key: "1w", weeks: 1 },
  { key: "1m", weeks: 4 },
  { key: "3m", weeks: 13 },
  { key: "6m", weeks: 26 },
] as const;

export type Range = (typeof RANGES)[number]["key"];

export function rangeOf(key: Range): (typeof RANGES)[number] {
  return RANGES.find((r) => r.key === key) ?? RANGES[2];
}

/** 小数 1 桁。-0.04 を「-0.0」と出さない */
export function formatOneDecimal(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return (rounded === 0 ? 0 : rounded).toFixed(1);
}

/** 差。+5.0、-1.2、0.0 の形 */
export function formatChange(value: number): string {
  const text = formatOneDecimal(value);
  return value > 0 && text !== "0.0" ? `+${text}` : text;
}

/** 秒を時間の小数 1 桁に。4028 秒 → "1.1" */
export function formatHours(sec: number): string {
  return (sec / 3600).toFixed(1);
}

/** 負荷は整数で、桁区切りを付ける。null（負荷の分かる回がない）は – */
export function formatLoad(load: number | null): string {
  return load === null ? "–" : Math.round(load).toLocaleString("en-US");
}
