import type { User } from "firebase/auth";
import { useEffect, useRef, useState } from "react";

import type { WorkoutSummary } from "../api";
import { getWorkouts } from "../lib/api";
import { useI18n } from "../i18n";
import { formatDateTime, formatDuration } from "../lib/format";

type Range = "4w" | "12w" | "all";

/** 1 回に取る件数。これだけ返ってきたら、まだ古い記録があるとみなして Load more を出す。 */
const PAGE_SIZE = 100;

/** 期間の選択肢。名前は辞書（workouts.ranges） */
const RANGES: { key: Range; weeks: number | null }[] = [
  { key: "4w", weeks: 4 },
  { key: "12w", weeks: 12 },
  { key: "all", weeks: null },
];

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

type Props = { user: User; onSelect: (id: number) => void };

/** 取ってきた一覧。どの期間（weeks、All は null）の結果かを一緒に持ち、
 * 今の期間と違えば表示に使わない。 */
type Page = {
  weeks: number | null;
  /** 1 ページ目で api が決めた始まり。続きはこれで取る。weeks を渡し直すと、日付を
   * またいだときに始まりが 1 日進み、境目の日の記録が続きから抜けるため */
  since: string | null;
  items: WorkoutSummary[];
  hasMore: boolean;
  loadingMore: boolean;
};

export default function WorkoutsPage({ user, onSelect }: Props) {
  const { m, locale } = useI18n();
  const w = m.workouts;
  const d = m.dashboard;
  const [range, setRange] = useState<Range>("4w");
  const [page, setPage] = useState<Page | null>(null);
  // 失敗そのものを持ち、文言は描くときに今の言語で出す
  const [error, setError] = useState<unknown>(null);
  // Retry で進める。期間が同じでも effect を走らせ直すため
  const [attempt, setAttempt] = useState(0);
  // 1 ページ目を取り直すたびに進める。Load more の応答は、始めたときと世代が違えば捨てる。
  // 期間の比較だけだと、別の期間に行って同じ期間に戻ったときに古い応答を見分けられない
  const generation = useRef(0);
  // Load more の連打よけ。disabled は描画のあとにしか効かないので、クリック直後にここで止める
  const loadingMoreNow = useRef(false);

  // 「直近 N 週」の始まりは api が設定のタイムゾーンで決める。端末の日付で決めると、
  // 端末と設定のタイムゾーンがずれたときに境目の 1 日がずれる（ダッシュボードと同じ）
  const weeks = RANGES.find((r) => r.key === range)?.weeks ?? null;

  // 今の期間の結果だけを表示する。期間を変えた直後は古い結果が残っていても Loading になる
  const current = page && page.weeks === weeks ? page : null;
  const items = current?.items ?? null;
  const hasMore = current?.hasMore ?? false;
  const loadingMore = current?.loadingMore ?? false;
  const since = current?.since ?? null;

  useEffect(() => {
    let cancelled = false;
    generation.current += 1;
    (async () => {
      try {
        const list = await getWorkouts(
          { weeks: weeks ?? undefined, limit: PAGE_SIZE },
          await user.getIdToken(),
        );
        if (cancelled) return;
        setError(null);
        setPage({
          weeks,
          since: list.since,
          items: list.items,
          hasMore: list.items.length === PAGE_SIZE,
          loadingMore: false,
        });
      } catch (e) {
        if (!cancelled) setError(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, weeks, attempt]);

  /** 失敗したあと、同じ期間の 1 ページ目を取り直す。 */
  function retry() {
    setError(null);
    setAttempt((n) => n + 1);
  }

  /** 表示中の一番古い記録より前を、同じ期間の中でもう 1 ページ取って末尾に足す。
   * 開始時刻と id の両方を渡し、開始時刻が同じ記録がページの境目にあっても抜けないようにする。 */
  async function loadMore() {
    if (!items || items.length === 0 || loadingMoreNow.current) return;
    loadingMoreNow.current = true;
    const started = generation.current;
    const last = items[items.length - 1];
    setPage((prev) => (prev ? { ...prev, loadingMore: true } : prev));
    try {
      const list = await getWorkouts(
        {
          since: since ?? undefined,
          until: last.started_at,
          before_id: last.id,
          limit: PAGE_SIZE,
        },
        await user.getIdToken(),
      );
      if (started !== generation.current) return;
      setPage((prev) =>
        prev
          ? {
              ...prev,
              items: [...prev.items, ...list.items],
              hasMore: list.items.length === PAGE_SIZE,
              loadingMore: false,
            }
          : prev,
      );
    } catch (e) {
      if (started !== generation.current) return;
      setError(e);
      setPage((prev) => (prev ? { ...prev, loadingMore: false } : prev));
    } finally {
      loadingMoreNow.current = false;
    }
  }

  return (
    <section className="page" aria-labelledby="workouts-heading">
      <h2 id="workouts-heading">{w.heading}</h2>
      <section className="card">
        <div className="card-head">
          <div role="group" aria-label={w.period} className="segmented compact">
            {RANGES.map((r) => (
              <button
                key={r.key}
                type="button"
                aria-pressed={range === r.key}
                onClick={() => setRange(r.key)}
              >
                {w.ranges[r.key] ?? r.key}
              </button>
            ))}
          </div>
          {items && items.length > 0 && (
            <p className="muted small">{w.count(items.length, hasMore)}</p>
          )}
        </div>

        {error !== null && (
          <p role="alert">
            {errorMessage(error, m.common.somethingWentWrong)}{" "}
            <button type="button" onClick={retry}>
              {m.common.retry}
            </button>
          </p>
        )}
        {items === null && error === null && (
          <p className="muted">{m.common.loading}</p>
        )}
        {items && items.length === 0 && <p className="muted">{w.noWorkouts}</p>}
        {items && items.length > 0 && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{d.date}</th>
                  <th>{d.sport}</th>
                  <th className="num">{d.time}</th>
                  <th className="num">{d.avgHr}</th>
                  <th className="num">{w.maxHr}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  // 行のどこを押しても詳細へ。キーボードでは種目のボタンで開く
                  <tr
                    key={row.id}
                    className="clickable"
                    onClick={() => onSelect(row.id)}
                  >
                    <td>{formatDateTime(row.started_at, locale)}</td>
                    <td>
                      <button
                        type="button"
                        className="row-link strong"
                        onClick={(e) => {
                          // 行の onClick と 2 回呼ばない
                          e.stopPropagation();
                          onSelect(row.id);
                        }}
                      >
                        {m.sports[row.sport] ?? row.sport}
                      </button>
                    </td>
                    <td className="num">
                      {formatDuration(row.duration_sec, m.duration)}
                    </td>
                    <td className="num">{row.avg_heart_rate ?? "–"}</td>
                    <td className="num">{row.max_heart_rate ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {hasMore && (
          <div className="card-foot">
            <button type="button" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? m.common.loading : w.loadMore}
            </button>
          </div>
        )}
      </section>
    </section>
  );
}
