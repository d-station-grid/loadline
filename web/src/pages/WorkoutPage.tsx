import type { User } from "firebase/auth";
import { useEffect, useState } from "react";

import type { HeartRateSample, NoteOut, WorkoutDetail } from "../api";
import ZoneBreakdown from "../components/ZoneBreakdown";
import { getNotes, getSettings, getWorkout } from "../lib/api";
import { zoneRows } from "../lib/charts";
import {
  dayInZone,
  formatDateTime,
  formatDuration,
  nextDay,
  SPORT_LABEL,
} from "../lib/format";

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

/** 強度の境目。設定が読めなければ線を引かない */
type Boundaries = { low: number | null; high: number | null };

/**
 * 1 分ごとの平均心拍を折れ線に。ライブラリは入れず、SVG だけで描く。
 * 強度の境目は点線で引く。縦の目盛りは 10 bpm ごと、横は 10 分ごと。
 */
function HeartRateChart({
  samples,
  boundaries,
}: {
  samples: HeartRateSample[];
  boundaries: Boundaries;
}) {
  if (samples.length < 2) {
    return <p className="muted">No heart rate data.</p>;
  }
  const width = 800;
  const height = 220;
  const left = 40;
  const right = 12;
  const top = 12;
  const bottom = 28;
  const values = samples.map((s) => s.avg_bpm);
  const lines = [boundaries.low, boundaries.high].filter(
    (v): v is number => v !== null,
  );
  // 境目の線も入るように、縦の範囲を 10 bpm 刻みで広げる
  const min = Math.floor((Math.min(...values, ...lines) - 5) / 10) * 10;
  const max = Math.ceil((Math.max(...values, ...lines) + 5) / 10) * 10;
  const x = (i: number) =>
    left + (i / (samples.length - 1)) * (width - left - right);
  const y = (v: number) =>
    top + (1 - (v - min) / (max - min)) * (height - top - bottom);
  const points = values
    .map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");
  const yTicks: number[] = [];
  for (let v = min; v <= max; v += max - min > 60 ? 20 : 10) yTicks.push(v);
  const xTicks: number[] = [];
  for (let m = 0; m < samples.length; m += 10) xTicks.push(m);
  const names = ["Low | Mid", "Mid | High"];
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Heart rate over time"
      className="hr-chart"
    >
      {yTicks.map((v) => (
        <g key={`y${v}`}>
          <line
            x1={left}
            x2={width - right}
            y1={y(v)}
            y2={y(v)}
            className="grid"
          />
          <text x={left - 8} y={y(v) + 4} textAnchor="end" className="tick">
            {v}
          </text>
        </g>
      ))}
      {xTicks.map((m) => (
        <text
          key={`x${m}`}
          x={x(m)}
          y={height - 8}
          textAnchor="middle"
          className="tick"
        >
          {m}'
        </text>
      ))}
      {[boundaries.low, boundaries.high].map((v, i) =>
        v === null ? null : (
          <g key={names[i]}>
            <line
              x1={left}
              x2={width - right}
              y1={y(v)}
              y2={y(v)}
              className="boundary"
            />
            <text x={left + 6} y={y(v) - 5} className="tick">
              {names[i]} {v}
            </text>
          </g>
        ),
      )}
      <polyline points={points} className="line" />
    </svg>
  );
}

/** 小さな数字の札。ラベルの下に数字と単位 */
function Tile({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="tile">
      <dt>{label}</dt>
      <dd>
        {value}
        {unit && value !== "–" && <span className="unit"> {unit}</span>}
      </dd>
    </div>
  );
}

type Props = { user: User; workoutId: number; onBack: () => void };

export default function WorkoutPage({ user, workoutId, onBack }: Props) {
  const [workout, setWorkout] = useState<WorkoutDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [boundaries, setBoundaries] = useState<Boundaries>({
    low: null,
    high: null,
  });
  // その日のメモ。読めなかったときと、まだ読んでいないときは undefined
  const [note, setNote] = useState<NoteOut | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await user.getIdToken();
        const w = await getWorkout(workoutId, token);
        if (cancelled) return;
        setWorkout(w);
        // 境目の線とメモの日は設定から。読めなくても詳細は出す
        try {
          const s = await getSettings(token);
          if (cancelled) return;
          setBoundaries({
            low: s.zone_boundary_1 ?? null,
            high: s.zone_boundary_2 ?? null,
          });
          // メモは利用者のタイムゾーンの日付で 1 日 1 件
          const day = dayInZone(w.started_at, s.timezone ?? "UTC");
          const notes = await getNotes(
            { since: day, until: nextDay(day) },
            token,
          );
          if (!cancelled) setNote(notes.items[0] ?? null);
        } catch {
          // 線とメモがないだけで、詳細は読めている
        }
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, workoutId]);

  const back = (
    <button type="button" className="link" onClick={onBack}>
      ‹ Workouts
    </button>
  );

  if (error) {
    return (
      <section className="page">
        {back}
        <p role="alert">{error}</p>
      </section>
    );
  }
  if (!workout) {
    return <p className="muted">Loading…</p>;
  }

  const rows = zoneRows(workout.zones);

  return (
    <section className="page" aria-labelledby="workout-heading">
      {back}
      <div>
        <h2 id="workout-heading">
          {SPORT_LABEL[workout.sport] ?? workout.sport}
        </h2>
        <p className="muted">{formatDateTime(workout.started_at)}</p>
      </div>

      <section className="card" aria-labelledby="intensity-heading">
        <h3 id="intensity-heading">Intensity</h3>
        <p className="muted small">
          Heart rate every minute. Lines mark your zone boundaries.
        </p>
        <HeartRateChart samples={workout.heart_rates} boundaries={boundaries} />
        <div className="split divided">
          <div>
            <h4>Time in each zone</h4>
            {rows ? (
              <ZoneBreakdown rows={rows} />
            ) : workout.heart_rates.length === 0 ? (
              <p className="muted small">
                No heart rate data for this workout.
              </p>
            ) : (
              <p className="muted small">
                Set your heart rate boundaries in Settings to see intensity.
              </p>
            )}
          </div>
          <dl className="tiles">
            <Tile label="Time" value={formatDuration(workout.duration_sec)} />
            <Tile
              label="Avg HR"
              value={String(workout.avg_heart_rate ?? "–")}
              unit="bpm"
            />
            <Tile
              label="Max HR"
              value={String(workout.max_heart_rate ?? "–")}
              unit="bpm"
            />
          </dl>
        </div>
      </section>

      {note !== undefined && (
        <section className="card" aria-labelledby="note-heading">
          <h3 id="note-heading">Note for this day</h3>
          {note ? (
            <p className="note-body">
              {note.label && <strong>{note.label} </strong>}
              {note.body}
            </p>
          ) : (
            <p className="muted">No note for this day.</p>
          )}
        </section>
      )}
    </section>
  );
}
