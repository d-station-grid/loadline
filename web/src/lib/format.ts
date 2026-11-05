/** 4028 秒 → "1h 07m"、1500 秒 → "25m"。0 より長く 1 分に丸めると 0 になる時間は "<1m"。 */
export function formatDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  if (h === 0 && m === 0 && sec > 0) return "<1m";
  return h > 0 ? `${h}h ${m.toString().padStart(2, "0")}m` : `${m}m`;
}

/** "2026-10-26" → "Oct 26"（端末の言語で）。日付だけの値なので、タイムゾーンでずらさない。 */
export function formatDay(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** ISO 8601 の日時を、端末の言語とタイムゾーンで短く。 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
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
