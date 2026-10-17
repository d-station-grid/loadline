import type { User } from "firebase/auth";
import { useEffect, useMemo, useState } from "react";

import type { Dashboard } from "../api";
import Chart from "../components/Chart";
import { getDashboard, type DashboardQuery } from "../lib/api";
import {
  loadOption,
  vo2maxOption,
  workoutsOption,
  zonesOption,
} from "../lib/charts";

type Range = "4w" | "12w" | "all";
type Sport = NonNullable<DashboardQuery["sport"]>;

const RANGES: { key: Range; label: string; weeks: number | null }[] = [
  { key: "4w", label: "Last 4 weeks", weeks: 4 },
  { key: "12w", label: "Last 12 weeks", weeks: 12 },
  { key: "all", label: "All", weeks: null },
];

const SPORTS: { key: Sport; label: string }[] = [
  { key: "all", label: "All sports" },
  { key: "ride", label: "Ride" },
  { key: "run", label: "Run" },
];

/** 期間の始まりの日（YYYY-MM-DD、端末のタイムゾーン）。「すべて」は api に任せて最初の記録の日から。 */
function sinceOf(weeks: number | null, now = new Date()): string | undefined {
  if (weeks === null) return undefined;
  const d = new Date(now);
  d.setDate(d.getDate() - weeks * 7);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

type Props = { user: User; onOpenSettings: () => void };

/** 取ってきた結果。どの条件の結果かを一緒に持ち、今の条件と違えば表示に使わない。 */
type Result = { key: string; data: Dashboard };

export default function DashboardPage({ user, onOpenSettings }: Props) {
  const [range, setRange] = useState<Range>("12w");
  const [sport, setSport] = useState<Sport>("all");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Retry で進める。条件が同じでも effect を走らせ直すため
  const [attempt, setAttempt] = useState(0);

  const weeks = RANGES.find((r) => r.key === range)?.weeks ?? null;
  const since = useMemo(() => sinceOf(weeks), [weeks]);
  const key = `${since ?? "all"}|${sport}`;
  const data = result && result.key === key ? result.data : null;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const dashboard = await getDashboard(
          { since, sport },
          await user.getIdToken(),
        );
        if (cancelled) return;
        setError(null);
        setResult({ key: `${since ?? "all"}|${sport}`, data: dashboard });
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, since, sport, attempt]);

  // option は応答が変わったときだけ作り直す。毎回作ると Chart が描き直してしまう
  const load = useMemo(() => (data ? loadOption(data.days) : null), [data]);
  const vo2max = useMemo(
    () => (data ? vo2maxOption(data.vo2max) : null),
    [data],
  );
  const zones = useMemo(() => (data ? zonesOption(data.zones) : null), [data]);
  const workouts = useMemo(
    () => (data ? workoutsOption(data.workouts) : null),
    [data],
  );

  const today = data?.days.at(-1);
  // 散布図に置ける回。負荷は心拍、高強度の時間は境目がないと出ない
  const plottable =
    data?.workouts.some((w) => w.load !== null && w.high_sec !== null) ?? false;

  function retry() {
    setError(null);
    setAttempt((n) => n + 1);
  }

  return (
    <section>
      <h2>Dashboard</h2>
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
      <div role="group" aria-label="Sport">
        {SPORTS.map((s) => (
          <button
            key={s.key}
            type="button"
            aria-pressed={sport === s.key}
            onClick={() => setSport(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert">
          {error}{" "}
          <button type="button" onClick={retry}>
            Retry
          </button>
        </p>
      )}
      {data === null && !error && <p>Loading…</p>}

      {data && (
        <>
          {data.needs_heart_rate_settings ? (
            <p>
              Set your max and resting heart rate to see training load.{" "}
              <button type="button" onClick={onOpenSettings}>
                Open settings
              </button>
            </p>
          ) : (
            <>
              {today && (
                <dl aria-label="Today">
                  <dt>Fitness</dt>
                  <dd>{today.fitness.toFixed(1)}</dd>
                  <dt>Fatigue</dt>
                  <dd>{today.fatigue.toFixed(1)}</dd>
                  <dt>Headroom</dt>
                  <dd>{today.headroom.toFixed(1)}</dd>
                </dl>
              )}
              <h3>Fitness, fatigue and load</h3>
              <p>Fitness and fatigue include every sport.</p>
              {load && <Chart option={load} />}
            </>
          )}

          <h3>VO2max</h3>
          {data.vo2max.length === 0 ? (
            <p>No VO2max in this period.</p>
          ) : (
            vo2max && <Chart option={vo2max} />
          )}

          <h3>Time by intensity</h3>
          {zones ? (
            <Chart option={zones} height={220} />
          ) : (
            <p>
              Needs zone boundaries in settings and heart rate on every workout
              in this period.
            </p>
          )}

          <h3>Load and high-intensity time per workout</h3>
          {data.workouts.length === 0 ? (
            <p>No workouts in this period.</p>
          ) : !plottable ? (
            <p>
              Needs zone boundaries in settings and heart rate on the workouts.
            </p>
          ) : (
            workouts && <Chart option={workouts} />
          )}
        </>
      )}
    </section>
  );
}
