import type { User } from "firebase/auth";
import { useEffect, useMemo, useState } from "react";

import type { Dashboard, NoteOut, WorkoutSummary } from "../api";
import Chart from "../components/Chart";
import Notes from "../components/Notes";
import Review from "../components/Review";
import { getDashboard, getWorkouts, type DashboardQuery } from "../lib/api";
import {
  type ZoneRow,
  TREND_CHART_HEIGHT,
  trendOption,
  workoutsOption,
  zoneRows,
} from "../lib/charts";
import {
  formatDateTime,
  formatDay,
  formatDuration,
  SPORT_LABEL,
} from "../lib/format";

type Range = "4w" | "12w" | "all";
type Sport = NonNullable<DashboardQuery["sport"]>;

const RANGES: { key: Range; label: string; weeks: number | null }[] = [
  { key: "4w", label: "4 weeks", weeks: 4 },
  { key: "12w", label: "12 weeks", weeks: 12 },
  { key: "all", label: "All", weeks: null },
];

const SPORTS: { key: Sport; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ride", label: "Ride" },
  { key: "run", label: "Run" },
];

/** Recent workouts に出す件数 */
const RECENT_COUNT = 3;

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

function weeksOf(range: Range): number | null {
  return RANGES.find((r) => r.key === range)?.weeks ?? null;
}

/** 取ってきた結果。どの条件の結果かを一緒に持ち、今の条件と違えば表示に使わない。 */
type Result = { key: string; data: Dashboard };

/**
 * GET /dashboard を条件ごとに読む。期間は週の数だけ渡し、始まりの日は api が設定の
 * タイムゾーンで決める。「すべて」は何も渡さず、api が最初の記録の日から返す。
 * 条件を変えた直後は、前の条件の結果を返さない（data は null）。
 * enabled が false の間は読まない。ほかの欄と同じ条件で、その結果を使い回すとき。
 */
function useDashboard(
  user: User,
  weeks: number | null,
  sport: Sport,
  enabled = true,
) {
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Retry で進める。条件が同じでも effect を走らせ直すため
  const [attempt, setAttempt] = useState(0);
  const key = `${weeks ?? "all"}|${sport}`;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      try {
        const dashboard = await getDashboard(
          { weeks: weeks ?? undefined, sport },
          await user.getIdToken(),
        );
        if (cancelled) return;
        setError(null);
        setResult({ key: `${weeks ?? "all"}|${sport}`, data: dashboard });
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, weeks, sport, attempt, enabled]);

  return {
    data: result && result.key === key ? result.data : null,
    // メモの欄は、読み込み直す間も前の結果の期間で出し続ける
    last: result?.data ?? null,
    error,
    retry: () => {
      setError(null);
      setAttempt((n) => n + 1);
    },
  };
}

type SegmentedProps<K extends string> = {
  label: string;
  /** カードの中に置く小さな形 */
  compact?: boolean;
  options: { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
};

/** ボタンをつなげた切り替え。選んでいるものは aria-pressed で示し、黒地に白で出す */
function Segmented<K extends string>({
  label,
  compact = false,
  options,
  value,
  onChange,
}: SegmentedProps<K>) {
  return (
    <div
      role="group"
      aria-label={label}
      className={compact ? "segmented compact" : "segmented"}
    >
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={value === o.key}
          onClick={() => onChange(o.key)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function ErrorLine({ error, retry }: { error: string; retry: () => void }) {
  return (
    <p role="alert" className="error">
      {error}{" "}
      <button type="button" onClick={retry}>
        Retry
      </button>
    </p>
  );
}

type Props = {
  user: User;
  onOpenSettings: () => void;
  onOpenWorkouts: () => void;
  onOpenWorkout: (id: number) => void;
};

export default function DashboardPage({
  user,
  onOpenSettings,
  onOpenWorkouts,
  onOpenWorkout,
}: Props) {
  const [range, setRange] = useState<Range>("12w");
  // Intensity の欄だけの条件。上の期間とは別に選べる
  const [intensityRange, setIntensityRange] = useState<Range>("12w");
  const [intensitySport, setIntensitySport] = useState<Sport>("all");
  // Notes が読んだ期間のメモ。ラベルのある日にチャートの点線を出す
  const [notes, setNotes] = useState<NoteOut[]>([]);

  // 数字のカードとチャートは全種目。体力と疲労は種目で絞らないため（api も同じ）
  const main = useDashboard(user, weeksOf(range), "all");
  // Intensity の条件が上と同じ間は、上の結果を使い、もう 1 回は読まない
  const sameAsMain = intensityRange === range && intensitySport === "all";
  const own = useDashboard(
    user,
    weeksOf(intensityRange),
    intensitySport,
    !sameAsMain,
  );
  const intensity = sameAsMain ? main : own;
  const data = main.data;

  // option は応答が変わったときだけ作り直す。毎回作ると Chart が描き直してしまう
  const trend = useMemo(
    () =>
      data
        ? trendOption(data.days, data.vo2max, notes, {
            since: data.since,
            until: data.until,
          })
        : null,
    [data, notes],
  );

  const today = data?.days.at(-1);
  // 最新の VO2max。api が日付の順に返すので、最後の 1 件
  const latestVo2max = data?.vo2max.at(-1);
  // 心拍のないワークアウトを含む日。負荷 0 として数えるので、体力と疲労は低めに出る
  const daysWithoutHeartRate =
    data?.days.filter((d) => d.load === null).length ?? 0;

  return (
    <section className="dashboard" aria-labelledby="dashboard-heading">
      <div className="page-head">
        <h2 id="dashboard-heading">Dashboard</h2>
        <Segmented
          label="Period"
          options={RANGES}
          value={range}
          onChange={setRange}
        />
      </div>

      {/* 振り返りは期間の切り替えに左右されない。#41 でアバターと右下に重ねるまで、ここに置く */}
      <Review user={user} onOpenSettings={onOpenSettings} />

      {main.error && <ErrorLine error={main.error} retry={main.retry} />}
      {data === null && !main.error && <p className="muted">Loading…</p>}

      {data && (
        <>
          <dl className="stats" aria-label="Latest">
            <Stat kind="fitness" label="Fitness" value={today?.fitness} />
            <Stat kind="fatigue" label="Fatigue" value={today?.fatigue} />
            {/* api の headroom を、画面では Form と呼ぶ */}
            <Stat kind="form" label="Form" value={today?.headroom} />
            <Stat
              kind="vo2max"
              label="VO2max"
              value={latestVo2max?.value}
              // 期間の最新の測定。今日の値ではないので、測った日を添える
              note={latestVo2max && formatDay(latestVo2max.day)}
            />
          </dl>

          <section className="card" aria-labelledby="trend-heading">
            <div className="card-head">
              <h3 id="trend-heading">Fitness, fatigue and VO2max</h3>
            </div>
            {data.needs_heart_rate_settings ? (
              <p className="notice">
                Set your max and resting heart rate to see training load.{" "}
                <button type="button" onClick={onOpenSettings}>
                  Open settings
                </button>
              </p>
            ) : (
              <p className="muted small">
                Fitness and fatigue include every sport.
              </p>
            )}
            {trend && <Chart option={trend} height={TREND_CHART_HEIGHT} />}
            {data.vo2max.length === 0 && (
              <p className="muted small">No VO2max in this period.</p>
            )}
            {daysWithoutHeartRate > 0 && (
              <p className="muted small">
                ▲ marks {daysWithoutHeartRate} day(s) with a workout that has no
                heart rate. Their load counts as 0, so fitness and fatigue read
                low.
              </p>
            )}
          </section>
        </>
      )}

      {/* Intensity の欄は自分の条件で読むので、上の読み込みとは別に出す */}
      <IntensityCard
        data={intensity.data}
        error={intensity.error}
        retry={intensity.retry}
        range={intensityRange}
        sport={intensitySport}
        onRange={setIntensityRange}
        onSport={setIntensitySport}
      />

      <RecentWorkouts
        user={user}
        // 期間を切り替えて読み込み直す間も、前の結果の負荷で出し続ける
        loads={main.last?.workouts ?? []}
        onOpenWorkouts={onOpenWorkouts}
        onOpenWorkout={onOpenWorkout}
      />

      {/* 期間を切り替えて読み込み直す間も、前の結果で出し続ける。書きかけのメモを消さないため */}
      {main.last && (
        <div className="card">
          <Notes
            user={user}
            since={main.last.since}
            today={main.last.until}
            onNotesChange={setNotes}
          />
        </div>
      )}
    </section>
  );
}

type StatProps = {
  /** ラベルの前の線の色を決める */
  kind: "fitness" | "fatigue" | "form" | "vo2max";
  label: string;
  value: number | undefined;
  /** 数字の下に小さく添える文 */
  note?: string;
};

/** 小数 1 桁。チャートと同じ桁にする。-0.04 を「-0.0」と出さない */
function formatStat(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return (rounded === 0 ? 0 : rounded).toFixed(1);
}

/** 小さなラベルの下に大きな数字。値がなければ – */
function Stat({ kind, label, value, note }: StatProps) {
  return (
    <div className={`stat ${kind}`}>
      <dt>{label}</dt>
      <dd>
        {value === undefined ? "–" : formatStat(value)}
        {note && <span className="stat-note">{note}</span>}
      </dd>
    </div>
  );
}

type IntensityProps = {
  data: Dashboard | null;
  error: string | null;
  retry: () => void;
  range: Range;
  sport: Sport;
  onRange: (range: Range) => void;
  onSport: (sport: Sport) => void;
};

/** 強度ごとの時間と、1 回ごとの負荷と高強度の時間。種目と期間はこの欄だけで選ぶ */
function IntensityCard({
  data,
  error,
  retry,
  range,
  sport,
  onRange,
  onSport,
}: IntensityProps) {
  const zones = data ? zoneRows(data.zones) : null;
  const scatter = useMemo(
    () => (data ? workoutsOption(data.workouts) : null),
    [data],
  );
  // 散布図に置ける回。負荷は心拍、高強度の時間は境目がないと出ない
  const plottable =
    data?.workouts.some((w) => w.load !== null && w.high_sec !== null) ?? false;

  return (
    <section className="card" aria-labelledby="intensity-heading">
      <div className="card-head">
        <h3 id="intensity-heading">Intensity</h3>
        <div className="card-tools">
          <Segmented
            compact
            label="Intensity sport"
            options={SPORTS}
            value={sport}
            onChange={onSport}
          />
          <Segmented
            compact
            label="Intensity period"
            options={RANGES}
            value={range}
            onChange={onRange}
          />
        </div>
      </div>

      {error && <ErrorLine error={error} retry={retry} />}
      {data === null && !error && <p className="muted">Loading…</p>}
      {data &&
        (data.workouts.length === 0 ? (
          <p className="muted">No workouts in this period.</p>
        ) : (
          <div className="split">
            <div>
              <h4>Time in each zone</h4>
              {zones ? (
                <ZoneBreakdown rows={zones} />
              ) : (
                <p className="muted small">
                  Needs zone boundaries in settings and heart rate on every
                  workout in this period.
                </p>
              )}
            </div>
            <div>
              <h4>Load and time in High</h4>
              {plottable && scatter ? (
                <Chart option={scatter} height={240} />
              ) : (
                <p className="muted small">
                  Needs zone boundaries in settings and heart rate on the
                  workouts.
                </p>
              )}
            </div>
          </div>
        ))}
    </section>
  );
}

/** 1 本の帯を強度ごとに塗り分け、下に時間と割合を並べる */
function ZoneBreakdown({ rows }: { rows: ZoneRow[] }) {
  return (
    <>
      <div className="zone-bar" aria-hidden="true">
        {rows.map((r) => (
          <span
            key={r.key}
            style={{ width: `${r.width}%`, background: r.color }}
          />
        ))}
      </div>
      <ul className="zone-list" aria-label="Time in each zone">
        {rows.map((r) => (
          <li key={r.key}>
            <span className="swatch" style={{ background: r.color }} />
            <span>{r.label}</span>
            <span className="num">{formatDuration(r.sec)}</span>
            <span className="num share">{r.percent}%</span>
          </li>
        ))}
      </ul>
    </>
  );
}

type RecentProps = {
  user: User;
  /** ダッシュボードの期間にある回の負荷。id で引く。期間の外の回は –、心拍のない回は No HR */
  loads: Dashboard["workouts"];
  onOpenWorkouts: () => void;
  onOpenWorkout: (id: number) => void;
};

/** 直近のワークアウト。行を押すと詳細へ、See all で一覧へ */
function RecentWorkouts({
  user,
  loads,
  onOpenWorkouts,
  onOpenWorkout,
}: RecentProps) {
  const [items, setItems] = useState<WorkoutSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await getWorkouts(
          { limit: RECENT_COUNT },
          await user.getIdToken(),
        );
        if (cancelled) return;
        setError(null);
        setItems(list.items);
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, attempt]);

  const loadById = new Map(loads.map((w) => [w.id, w.load]));

  return (
    <section className="card" aria-labelledby="recent-heading">
      <div className="card-head">
        <h3 id="recent-heading">Recent workouts</h3>
        <button type="button" className="link" onClick={onOpenWorkouts}>
          See all workouts ›
        </button>
      </div>
      {error && (
        <ErrorLine
          error={error}
          retry={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
        />
      )}
      {items === null && !error && <p className="muted">Loading…</p>}
      {items?.length === 0 && <p className="muted">No workouts yet.</p>}
      {items && items.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Sport</th>
              <th>Time</th>
              <th className="num">Avg HR</th>
              <th className="num">Load</th>
            </tr>
          </thead>
          <tbody>
            {items.map((w) => {
              const load = loadById.get(w.id);
              return (
                // 行のどこを押しても詳細へ。キーボードでは日付のボタンで開く
                <tr
                  key={w.id}
                  className="clickable"
                  onClick={() => onOpenWorkout(w.id)}
                >
                  <td>
                    <button type="button" className="row-link">
                      {formatDateTime(w.started_at)}
                    </button>
                  </td>
                  <td>{SPORT_LABEL[w.sport] ?? w.sport}</td>
                  <td>{formatDuration(w.duration_sec)}</td>
                  <td className="num">{w.avg_heart_rate ?? "–"}</td>
                  <td className="num">
                    <LoadCell load={load} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** 負荷の欄。期間の外で分からない回と、心拍がなくて計算できない回を分けて出す */
function LoadCell({ load }: { load: number | null | undefined }) {
  if (load === undefined) {
    return <span title="Outside the dashboard period">–</span>;
  }
  if (load === null) {
    return (
      <span className="muted" title="No heart rate, so load can't be computed">
        No HR
      </span>
    );
  }
  return <>{load.toFixed(0)}</>;
}
