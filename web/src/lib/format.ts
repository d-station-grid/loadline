import { en, type Messages } from "../i18n/messages";

/**
 * 4028 秒 → "1h 07m"、1500 秒 → "25m"。0 より長く 1 分に丸めると 0 になる時間は "<1m"。
 * 書き方は画面の言語の文言（日本語なら "1時間07分"）。省けば英語
 */
export function formatDuration(
  sec: number,
  words: Messages["duration"] = en.duration,
): string {
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  if (h === 0 && m === 0 && sec > 0) return words.lessThanMinute;
  return h > 0
    ? words.hoursMinutes(h, m.toString().padStart(2, "0"))
    : words.minutes(m);
}

/**
 * "2026-10-26" → "Oct 26"。日付だけの値なので、タイムゾーンでずらさない。
 * locale は画面の言語のロケール（"ja-JP" なら "10月26日"）。省けば端末の言語
 */
export function formatDay(day: string, locale?: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString(locale, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** ISO 8601 の日時を、端末のタイムゾーンで短く。locale を省けば端末の言語 */
export function formatDateTime(iso: string, locale?: string): string {
  return new Date(iso).toLocaleString(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export const SPORT_LABEL: Record<string, string> = { ride: "Ride", run: "Run" };

/** その時刻が、そのタイムゾーンで何日か（YYYY-MM-DD）。 */
export function dayInZone(iso: string, timeZone: string): string {
  // en-CA は YYYY-MM-DD の形で出す
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
}

/** "2026-10-31" → "2026-11-01"。日付だけを UTC で数えるので、夏時間でずれない。 */
export function nextDay(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}
