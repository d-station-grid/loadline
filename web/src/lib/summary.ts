import type { Form } from "../api";

// ダッシュボードの数字の書き方。比べる計算は api がしているので、ここでは書き方だけを決める。

/** 期間の選択肢。週の数を api に渡す。span は「last 3 months」「prev 3 months」の言い方 */
export const RANGES = [
  { key: "1w", label: "1W", weeks: 1, span: "week" },
  { key: "1m", label: "1M", weeks: 4, span: "month" },
  { key: "3m", label: "3M", weeks: 13, span: "3 months" },
  { key: "6m", label: "6M", weeks: 26, span: "6 months" },
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

/**
 * Form の一言。api の form は、期間の最後の日の余力 ÷ 体力 だけを見る。
 * 何週か休んで疲労が抜けても fresh になるので、fresh は「疲労が抜けている」とだけ言い、
 * 練習が順調だとは読めない言い方にする。
 */
export const FORM_LABEL: Record<Form, string> = {
  fatigued: "Tired — ease off",
  fresh: "Fresh — fatigue has cleared",
  steady: "Balanced",
  not_enough_data: "Not enough data to judge",
};

/** 秒を時間の小数 1 桁に。4028 秒 → "1.1" */
export function formatHours(sec: number): string {
  return (sec / 3600).toFixed(1);
}

/** 負荷は整数で、桁区切りを付ける。null（負荷の分かる回がない）は – */
export function formatLoad(load: number | null): string {
  return load === null ? "–" : Math.round(load).toLocaleString("en-US");
}
