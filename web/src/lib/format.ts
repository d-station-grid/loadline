/** 4028 秒 → "1h 07m"、1500 秒 → "25m"。 */
export function formatDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m.toString().padStart(2, "0")}m` : `${m}m`;
}

/** ISO 8601 の日時を、端末の言語とタイムゾーンで短く。 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export const SPORT_LABEL: Record<string, string> = { ride: "Ride", run: "Run" };
