import type { User } from "firebase/auth";
import { useEffect, useState } from "react";

import type { WorkoutSummary } from "../api";
import { getWorkouts } from "../lib/api";
import { formatDateTime, formatDuration, SPORT_LABEL } from "../lib/format";

type Range = "4w" | "12w" | "all";

const RANGES: { key: Range; label: string; weeks: number | null }[] = [
  { key: "4w", label: "Last 4 weeks", weeks: 4 },
  { key: "12w", label: "Last 12 weeks", weeks: 12 },
  { key: "all", label: "All", weeks: null },
];

/** 期間の始まり。「直近 N 週」は今日から N 週前の 0 時（端末のタイムゾーン）。 */
function sinceOf(weeks: number | null, now = new Date()): string | undefined {
  if (weeks === null) return undefined;
  const d = new Date(now);
  d.setDate(d.getDate() - weeks * 7);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

type Props = { user: User; onSelect: (id: number) => void };

export default function WorkoutsPage({ user, onSelect }: Props) {
  const [range, setRange] = useState<Range>("4w");
  const [items, setItems] = useState<WorkoutSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const weeks = RANGES.find((r) => r.key === range)?.weeks ?? null;
    (async () => {
      try {
        const list = await getWorkouts(
          { since: sinceOf(weeks) },
          await user.getIdToken(),
        );
        if (!cancelled) setItems(list.items);
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, range]);

  return (
    <section>
      <h2>Workouts</h2>
      <div role="group" aria-label="Period">
        {RANGES.map((r) => (
          <button
            key={r.key}
            type="button"
            aria-pressed={range === r.key}
            onClick={() => setRange(r.key)}
          >
            {r.label}
          </button>
        ))}
      </div>

      {error && <p role="alert">{error}</p>}
      {items === null && !error && <p>Loading…</p>}
      {items && items.length === 0 && <p>No workouts in this period.</p>}
      {items && items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Sport</th>
              <th>Start</th>
              <th>Duration</th>
              <th>Avg HR</th>
              <th>Max HR</th>
            </tr>
          </thead>
          <tbody>
            {items.map((w) => (
              <tr key={w.id}>
                <td>
                  <button type="button" onClick={() => onSelect(w.id)}>
                    {SPORT_LABEL[w.sport] ?? w.sport}
                  </button>
                </td>
                <td>{formatDateTime(w.started_at)}</td>
                <td>{formatDuration(w.duration_sec)}</td>
                <td>{w.avg_heart_rate ?? "–"}</td>
                <td>{w.max_heart_rate ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
