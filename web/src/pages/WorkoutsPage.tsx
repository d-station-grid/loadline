import type { User } from "firebase/auth";
import { useEffect, useMemo, useState } from "react";

import type { WorkoutSummary } from "../api";
import { getWorkouts } from "../lib/api";
import { formatDateTime, formatDuration, SPORT_LABEL } from "../lib/format";

type Range = "4w" | "12w" | "all";

/** 1 回に取る件数。これだけ返ってきたら、まだ古い記録があるとみなして Load more を出す。 */
const PAGE_SIZE = 100;

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

/** 取ってきた一覧。どの期間（since）の結果かを一緒に持ち、今の期間と違えば表示に使わない。 */
type Page = {
  since: string | undefined;
  items: WorkoutSummary[];
  hasMore: boolean;
};

export default function WorkoutsPage({ user, onSelect }: Props) {
  const [range, setRange] = useState<Range>("4w");
  const [page, setPage] = useState<Page | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const weeks = RANGES.find((r) => r.key === range)?.weeks ?? null;
  const since = useMemo(() => sinceOf(weeks), [weeks]);

  // 今の期間の結果だけを表示する。期間を変えた直後は古い結果が残っていても Loading になる
  const items = page && page.since === since ? page.items : null;
  const hasMore = page && page.since === since ? page.hasMore : false;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await getWorkouts(
          { since, limit: PAGE_SIZE },
          await user.getIdToken(),
        );
        if (cancelled) return;
        setPage({
          since,
          items: list.items,
          hasMore: list.items.length === PAGE_SIZE,
        });
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, since]);

  /** 表示中の一番古い記録より前を、同じ期間の中でもう 1 ページ取って末尾に足す。 */
  async function loadMore() {
    if (!items || items.length === 0) return;
    setLoadingMore(true);
    try {
      const list = await getWorkouts(
        { since, until: items[items.length - 1].started_at, limit: PAGE_SIZE },
        await user.getIdToken(),
      );
      // 待っている間に期間が変わっていたら、この応答は捨てる
      setPage((prev) =>
        prev && prev.since === since
          ? {
              since,
              items: [...prev.items, ...list.items],
              hasMore: list.items.length === PAGE_SIZE,
            }
          : prev,
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoadingMore(false);
    }
  }

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
      {hasMore && (
        <button type="button" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}
