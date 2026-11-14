import type { User } from "firebase/auth";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import type {
  Dashboard,
  NoteOut,
  SportViews,
  SportView,
  WorkoutSummary,
} from "../api";
import Chart from "../components/Chart";
import Notes from "../components/Notes";
import Review from "../components/Review";
import ZoneBreakdown from "../components/ZoneBreakdown";
import { getWorkouts } from "../lib/api";
import {
  TREND_CHART_HEIGHT,
  trendOption,
  workoutsOption,
  zoneRows,
  zoneWeeksOption,
} from "../lib/charts";
import {
  formatDateTime,
  formatDay,
  formatDuration,
  SPORT_LABEL,
} from "../lib/format";
import { EMPTY_NOTE_DRAFT, type NoteDraft } from "../lib/noteDraft";
import { useDashboard, useNotes } from "../lib/queries";
import {
  FORM_LABEL,
  formatChange,
  formatHours,
  formatLoad,
  formatOneDecimal,
  RANGES,
  rangeOf,
  type Range,
} from "../lib/summary";

type Sport = keyof SportViews;

/** 最初に選ばれている期間。Figma と同じ 3M */
const DEFAULT_RANGE: Range = "3m";

const SPORTS: { key: Sport; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ride", label: "Ride" },
  { key: "run", label: "Run" },
];

/** メモがまだ届いていないときの空の一覧。描くたびに新しい配列を作ると、チャートを描き直すため */
const NO_NOTES: NoteOut[] = [];

/** Recent workouts に出す件数 */
const RECENT_COUNT = 3;

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

type SegmentedProps<K extends string> = {
  label: string;
  /** カードの中に置く小さな形 */
  compact?: boolean;
  options: readonly { key: K; label: string }[];
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
  const [range, setRange] = useState<Range>(DEFAULT_RANGE);
  // Intensity の欄だけの条件。上の期間とは別に選べる
  const [intensityRange, setIntensityRange] = useState<Range>(DEFAULT_RANGE);
  const [intensitySport, setIntensitySport] = useState<Sport>("all");
  // メモのモーダル。閉じたら Notes ごと外す。書きかけは noteDraft に残す
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState<NoteDraft>(EMPTY_NOTE_DRAFT);
  const [notePick, setNotePick] = useState<{ date: string; at: number }>();

  const mainWeeks = rangeOf(range).weeks;
  const intensityWeeks = rangeOf(intensityRange).weeks;
  // 上の期間と Intensity は同じ SWR のキャッシュを見る。同じ期間なら 1 回だけ読み、
  // 片方の期間を変えても、もう片方は持っている結果をそのまま使う
  const main = useDashboard(user, mainWeeks);
  const intensity = useDashboard(user, intensityWeeks);
  // 読み直しに失敗したら、SWR は前の結果を残すが、画面はエラーと Retry だけにする。
  // 古い数字を今の値のように見せないため
  const data = main.error ? null : (main.data ?? null);

  // 上の期間を切り替えて読み込む間も、メモの欄と Recent workouts の負荷は前の結果で出す
  // 描画の中で前の結果を覚える（React の「前の描画の情報を持つ」書き方）
  const [previous, setPrevious] = useState<Dashboard | null>(null);
  if (data && data !== previous) setPrevious(data);
  const last = data ?? previous;
  // メモのモーダルと同じキャッシュ。ラベルのある日にチャートの点線を出す
  const notes = useNotes(user, last?.since).data ?? NO_NOTES;

  /** メモのモーダルを、その日を選んで開く */
  function openNote(day: string) {
    setNotePick({ date: day, at: Date.now() });
    setNoteOpen(true);
  }

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
        <div className="page-title">
          <h2 id="dashboard-heading">Dashboard</h2>
          {/* 取り込みが最後に成功した日時。まだない人（デモも）には出さない */}
          {last?.last_received_at && (
            <span className="muted small">
              Last received · {formatDateTime(last.last_received_at)}
            </span>
          )}
        </div>
        <div className="card-tools">
          <Segmented
            label="Period"
            options={RANGES}
            value={range}
            onChange={setRange}
          />
          <button
            type="button"
            disabled={!last}
            onClick={() => last && openNote(last.until)}
          >
            + Note
          </button>
        </div>
      </div>

      {/* 週次レビューは期間の切り替えに左右されない。画面の右下に浮かせて出す（位置は CSS）。
          読み上げの順で、数字より先に届くよう、ここに置く */}
      <Review user={user} onOpenSettings={onOpenSettings} />

      {main.error && (
        <ErrorLine
          error={errorMessage(main.error)}
          retry={() => void main.mutate()}
        />
      )}
      {data === null && !main.error && <p className="muted">Loading…</p>}

      {data && (
        <>
          {/* 差は api の changes をそのまま出す。days の最初の日と比べ直さない（期間の初日との差ではない） */}
          <dl className="stats" aria-label="Latest">
            <Stat
              kind="fitness"
              label="Fitness"
              value={today?.fitness}
              note={vsLastWeek(data.changes.fitness)}
            />
            <Stat
              kind="fatigue"
              label="Fatigue"
              value={today?.fatigue}
              note={vsLastWeek(data.changes.fatigue)}
            />
            {/* api の headroom を、画面では Form と呼ぶ */}
            <Stat
              kind="form"
              label="Form"
              value={today?.headroom}
              note={data.form ? FORM_LABEL[data.form] : undefined}
            />
            <Stat
              kind="vo2max"
              label="VO2max"
              value={latestVo2max?.value}
              note={vo2maxNote(data)}
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
                Click a day to add a note. Notes with a label show on the chart.
                Fitness and fatigue include every sport.
              </p>
            )}
            {trend && (
              <Chart
                option={trend}
                height={TREND_CHART_HEIGHT}
                onDayClick={openNote}
              />
            )}
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
        data={
          intensity.error
            ? null
            : (intensity.data?.by_sport[intensitySport] ?? null)
        }
        error={intensity.error ? errorMessage(intensity.error) : null}
        retry={() => void intensity.mutate()}
        range={intensityRange}
        sport={intensitySport}
        onRange={setIntensityRange}
        onSport={setIntensitySport}
      />

      <RecentWorkouts
        user={user}
        // 期間を切り替えて読み込み直す間も、前の結果の負荷で出し続ける
        // 数字のカードと同じく全種目
        loads={last?.by_sport.all.workouts ?? []}
        onOpenWorkouts={onOpenWorkouts}
        onOpenWorkout={onOpenWorkout}
      />

      {/* 期間を切り替えて読み込み直す間も、前の結果の期間で開いたままにする */}
      {last && noteOpen && (
        <NoteDialog onClose={() => setNoteOpen(false)}>
          <Notes
            user={user}
            since={last.since}
            today={last.until}
            draft={noteDraft}
            onDraftChange={setNoteDraft}
            pick={notePick}
          />
        </NoteDialog>
      )}
    </section>
  );
}

type NoteDialogProps = {
  onClose: () => void;
  children: ReactNode;
};

/** モーダルの中で Tab が止まるもの */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * メモのモーダル。開いている間だけ描き、閉じたら外す。Esc、Close、外側を押すと閉じる。
 * 開いている間は Tab をモーダルの中で回し、閉じたら開く前の場所（「+ Note」など）にフォーカスを戻す。
 */
function NoteDialog({ onClose, children }: NoteDialogProps) {
  const box = useRef<HTMLDivElement>(null);
  // 閉じる関数が変わっても、開いている間の仕掛けは張り直さない
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    box.current?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      // フォーカスがどこにあっても、開いている間は Esc で閉じる
      if (e.key === "Escape") {
        e.preventDefault();
        close.current();
        return;
      }
      if (e.key !== "Tab" || !box.current) return;
      const items = Array.from(
        box.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      );
      if (items.length === 0) {
        e.preventDefault();
        box.current.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const inside = active instanceof Node && box.current.contains(active);
      if (
        e.shiftKey &&
        (!inside || active === first || active === box.current)
      ) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (!inside || active === last)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={box}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="notes-heading"
        tabIndex={-1}
      >
        {children}
        <div className="modal-actions">
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
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

/** Fitness と Fatigue の下の行。比べる値がなければ出さない */
function vsLastWeek(change: number | null): string | undefined {
  return change === null ? undefined : `${formatChange(change)} vs last week`;
}

/**
 * VO2max の下の行。期間の最新の測定は今日の値ではないので、測った日を添える。
 * 差は、api が比べた測定の日を「since」で書く。測定が空くと 4 週より前の測定と比べるので、
 * 「in 4 weeks」とは書かない。比べる測定がなければ、日付だけ。
 */
function vo2maxNote(data: Dashboard): string | undefined {
  const latest = data.vo2max.at(-1);
  if (!latest) return undefined;
  const day = formatDay(latest.day);
  const { vo2max: change, vo2max_since: since } = data.changes;
  return change === null || since === null
    ? day
    : `${formatChange(change)} since ${formatDay(since)} · ${day}`;
}

/** 小さなラベルの下に大きな数字。値がなければ – */
function Stat({ kind, label, value, note }: StatProps) {
  return (
    <div className={`stat ${kind}`}>
      <dt>{label}</dt>
      <dd>
        {value === undefined ? "–" : formatOneDecimal(value)}
        {note && <span className="stat-note">{note}</span>}
      </dd>
    </div>
  );
}

type IntensityProps = {
  /** 選んだ種目のぶん */
  data: SportView | null;
  error: string | null;
  retry: () => void;
  range: Range;
  sport: Sport;
  onRange: (range: Range) => void;
  onSport: (sport: Sport) => void;
};

/** 強度ごとの時間（週ごとと期間の合計）、1 回ごとの負荷と高強度の時間、期間の合計。種目と期間はこの欄だけで選ぶ */
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
  const weekly = useMemo(
    () => (data?.zone_weeks ? zoneWeeksOption(data.zone_weeks) : null),
    [data],
  );
  // 散布図に置ける回。負荷は心拍、高強度の時間は境目がないと出ない
  const plottable =
    data?.workouts.some((w) => w.load !== null && w.high_sec !== null) ?? false;
  // 心拍のない回を含む週。棒の ▲ の説明に使う
  const weeksWithoutZones =
    data?.zone_weeks?.filter((w) => w.workouts_without_zones > 0).length ?? 0;
  // 期間の心拍のない回。境目があるのに期間の合計が出ない理由
  const workoutsWithoutZones =
    data?.zone_weeks?.reduce((n, w) => n + w.workouts_without_zones, 0) ?? 0;
  const span = rangeOf(range).span;
  const sportLabel = SPORTS.find((s) => s.key === sport)?.label ?? sport;

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
        {data && (
          <span className="card-summary muted small">
            {sportLabel} · last {span} · {data.totals.workouts}
          </span>
        )}
      </div>

      {error && <ErrorLine error={error} retry={retry} />}
      {data === null && !error && <p className="muted">Loading…</p>}

      {data &&
        (data.workouts.length === 0 ? (
          <>
            <p className="muted">No workouts in this period.</p>
            <Totals data={data} span={span} />
          </>
        ) : (
          <>
            <div className="split">
              <div>
                <h4>Minutes in each zone · by week</h4>
                {weekly ? (
                  <>
                    <Chart option={weekly} height={240} />
                    {weeksWithoutZones > 0 && (
                      <p className="muted small">
                        ▲ marks {weeksWithoutZones} week(s) with a workout that
                        has no heart rate. Its minutes are left out.
                      </p>
                    )}
                  </>
                ) : (
                  <p className="muted small">
                    Needs zone boundaries in settings.
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
            <div className="split divided">
              <div>
                <h4>Time in each zone</h4>
                {zones ? (
                  <ZoneBreakdown rows={zones} />
                ) : data.zone_weeks ? (
                  // 境目はある。心拍のない回を外して足すと少なく見えるので、合計は出さない
                  <p className="muted small">
                    Not shown: {workoutsWithoutZones} workout(s) in this period
                    have no heart rate.
                  </p>
                ) : (
                  <p className="muted small">
                    Needs zone boundaries in settings.
                  </p>
                )}
              </div>
              <Totals data={data} span={span} />
            </div>
          </>
        ))}
    </section>
  );
}

/**
 * 期間の合計と、前の同じ長さの期間の値。数字は api の totals をそのまま出す。
 * 負荷は、回がなければ 0、回はあるのに負荷が 1 回も分からなければ –（null）。
 * 1 回あたりは api が負荷の分かる回の数で割った値で、ここで割り直さない。
 */
function Totals({ data, span }: { data: SportView; span: string }) {
  const now = data.totals;
  const prev = data.previous_totals;
  const prevLabel = `prev ${span}`;
  return (
    <div>
      <h4>Totals</h4>
      <dl className="totals" aria-label="Totals">
        <TotalTile
          label="Time"
          value={formatHours(now.total_sec)}
          unit="h"
          prev={`${prevLabel} · ${formatHours(prev.total_sec)} h`}
        />
        <TotalTile
          label="Workouts"
          value={String(now.workouts)}
          prev={`${prevLabel} · ${prev.workouts}`}
        />
        <TotalTile
          label="Load"
          value={formatLoad(now.load)}
          prev={`${prevLabel} · ${formatLoad(prev.load)}`}
        />
        <TotalTile
          label="Load per workout"
          value={formatLoad(now.load_per_workout)}
          prev={`${prevLabel} · ${formatLoad(prev.load_per_workout)}`}
        />
      </dl>
      {(now.workouts_without_load > 0 || prev.workouts_without_load > 0) && (
        <p className="muted small">
          Load leaves out workouts without heart rate:{" "}
          {now.workouts_without_load} in this period,{" "}
          {prev.workouts_without_load} in the previous one.
        </p>
      )}
    </div>
  );
}

type TotalTileProps = {
  label: string;
  value: string;
  unit?: string;
  prev: string;
};

function TotalTile({ label, value, unit, prev }: TotalTileProps) {
  return (
    <div className="total">
      <dt>{label}</dt>
      <dd>
        {value}
        {unit && <span className="total-unit"> {unit}</span>}
        <span className="total-prev">{prev}</span>
      </dd>
    </div>
  );
}

type RecentProps = {
  user: User;
  /** ダッシュボードの期間にある回の負荷。id で引く。期間の外の回は –、心拍のない回は No HR */
  loads: SportView["workouts"];
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
