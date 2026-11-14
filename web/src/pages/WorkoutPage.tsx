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
} from "../lib/format";
import { useI18n } from "../i18n";

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/** 強度の境目。設定が読めなければ線を引かない */
type Boundaries = { low: number | null; high: number | null };

/**
 * 1 分ごとの平均心拍を折れ線に。ライブラリは入れず、SVG だけで描く。
 * 強度の境目は点線で引く。縦の目盛りは 10 bpm ごと。
 * 横は最初のサンプルからの経過時間（分）。サンプルの番号で並べると、一時停止のぶんだけ Time とずれる。
 */
function HeartRateChart({
  samples,
  boundaries,
}: {
  samples: HeartRateSample[];
  boundaries: Boundaries;
}) {
  const { m } = useI18n();
  if (samples.length < 2) {
    return <p className="muted">{m.workout.chartNoHeartRate}</p>;
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
  // 最初のサンプルからの経過分。一時停止で抜けた分は、線が飛んでつながる
  const start = Date.parse(samples[0].recorded_at);
  const minutes = samples.map(
    (s) => (Date.parse(s.recorded_at) - start) / 60000,
  );
  const span = Math.max(minutes[minutes.length - 1], 1);
  const x = (m: number) => left + (m / span) * (width - left - right);
  const y = (v: number) =>
    top + (1 - (v - min) / (max - min)) * (height - top - bottom);
  const points = values
    .map((v, i) => `${x(minutes[i]).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");
  const yTicks: number[] = [];
  for (let v = min; v <= max; v += max - min > 60 ? 20 : 10) yTicks.push(v);
  const xTicks: number[] = [];
  // 長い回は目盛りを間引く
  const step = span > 180 ? 30 : span > 90 ? 20 : 10;
  for (let m = 0; m <= span; m += step) xTicks.push(m);
  const names = m.workout.boundaryNames;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={m.workout.chartLabel}
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
  const { m, locale } = useI18n();
  const t = m.workout;
  const d = m.dashboard;
  // 失敗そのものを持ち、文言は描くときに今の言語で出す
  const [error, setError] = useState<unknown>(null);
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
        if (!cancelled) setError(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, workoutId]);

  const back = (
    <button type="button" className="link" onClick={onBack}>
      {t.back}
    </button>
  );

  if (error !== null) {
    return (
      <section className="page">
        {back}
        <p role="alert">{errorMessage(error, m.common.somethingWentWrong)}</p>
      </section>
    );
  }
  if (!workout) {
    return <p className="muted">{m.common.loading}</p>;
  }

  const rows = zoneRows(workout.zones, m);

  return (
    <section className="page" aria-labelledby="workout-heading">
      {back}
      <div>
        <h2 id="workout-heading">{m.sports[workout.sport] ?? workout.sport}</h2>
        <p className="muted">{formatDateTime(workout.started_at, locale)}</p>
      </div>

      <section className="card" aria-labelledby="intensity-heading">
        <h3 id="intensity-heading">{t.intensity}</h3>
        <p className="muted small">{t.intensityHelp}</p>
        <HeartRateChart samples={workout.heart_rates} boundaries={boundaries} />
        <div className="split divided">
          <div>
            <h4>{t.timeInZone}</h4>
            {rows ? (
              <ZoneBreakdown rows={rows} />
            ) : workout.heart_rates.length === 0 ? (
              <p className="muted small">{t.noHeartRate}</p>
            ) : (
              <p className="muted small">{t.needsBoundaries}</p>
            )}
          </div>
          <dl className="tiles">
            <Tile
              label={d.time}
              value={formatDuration(workout.duration_sec, m.duration)}
            />
            <Tile
              label={d.avgHr}
              value={String(workout.avg_heart_rate ?? "–")}
              unit="bpm"
            />
            <Tile
              label={m.workouts.maxHr}
              value={String(workout.max_heart_rate ?? "–")}
              unit="bpm"
            />
          </dl>
        </div>
      </section>

      {note !== undefined && (
        <section className="card" aria-labelledby="note-heading">
          <h3 id="note-heading">{t.noteHeading}</h3>
          {note ? (
            <p className="note-body">
              {note.label && <strong>{note.label} </strong>}
              {note.body}
            </p>
          ) : (
            <p className="muted">{t.noNote}</p>
          )}
        </section>
      )}
    </section>
  );
}
