import type { User } from "firebase/auth";
import { useEffect, useState } from "react";

import type { HeartRateSample, WorkoutDetail } from "../api";
import { getWorkout } from "../lib/api";
import { formatDateTime, formatDuration, SPORT_LABEL } from "../lib/format";

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

/** 1 分ごとの平均心拍を折れ線に。ライブラリは入れず、SVG の polyline だけ。 */
function HeartRateChart({ samples }: { samples: HeartRateSample[] }) {
  if (samples.length < 2) {
    return <p>No heart rate data.</p>;
  }
  const width = 600;
  const height = 200;
  const pad = 24;
  const values = samples.map((s) => s.avg_bpm);
  const min = Math.min(...values) - 5;
  const max = Math.max(...values) + 5;
  const x = (i: number) => pad + (i / (samples.length - 1)) * (width - pad * 2);
  const y = (v: number) =>
    height - pad - ((v - min) / (max - min)) * (height - pad * 2);
  const points = values
    .map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Heart rate over time"
      style={{ width: "100%", maxWidth: width }}
    >
      <text x={pad} y={pad - 8} fontSize="12">
        {max - 5} bpm
      </text>
      <text x={pad} y={height - 4} fontSize="12">
        {min + 5} bpm
      </text>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

type Props = { user: User; workoutId: number; onBack: () => void };

export default function WorkoutPage({ user, workoutId, onBack }: Props) {
  const [workout, setWorkout] = useState<WorkoutDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const w = await getWorkout(workoutId, await user.getIdToken());
        if (!cancelled) setWorkout(w);
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, workoutId]);

  if (error) {
    return (
      <section>
        <button type="button" onClick={onBack}>
          ← Workouts
        </button>
        <p role="alert">{error}</p>
      </section>
    );
  }
  if (!workout) {
    return <p>Loading…</p>;
  }

  const zones = workout.zones;
  const total = zones ? zones.low + zones.mid + zones.high : 0;
  const pct = (sec: number) =>
    total > 0 ? Math.round((sec / total) * 100) : 0;

  return (
    <section>
      <button type="button" onClick={onBack}>
        ← Workouts
      </button>
      <h2>{SPORT_LABEL[workout.sport] ?? workout.sport}</h2>
      <p>{formatDateTime(workout.started_at)}</p>

      <dl>
        <dt>Duration</dt>
        <dd>{formatDuration(workout.duration_sec)}</dd>
        <dt>Avg HR</dt>
        <dd>{workout.avg_heart_rate ?? "–"}</dd>
        <dt>Max HR</dt>
        <dd>{workout.max_heart_rate ?? "–"}</dd>
      </dl>

      <h3>Heart rate</h3>
      <HeartRateChart samples={workout.heart_rates} />

      <h3>Intensity</h3>
      {zones ? (
        <ul>
          <li>
            Low: {formatDuration(zones.low)} ({pct(zones.low)}%)
          </li>
          <li>
            Mid: {formatDuration(zones.mid)} ({pct(zones.mid)}%)
          </li>
          <li>
            High: {formatDuration(zones.high)} ({pct(zones.high)}%)
          </li>
        </ul>
      ) : (
        <p>Set your heart rate boundaries in Settings to see intensity.</p>
      )}
    </section>
  );
}
