import type { User } from "firebase/auth";
import { useEffect, useRef, useState } from "react";

import type { WeeklyReviewOut } from "../api";
import {
  ApiError,
  createReview,
  getCurrentReview,
  selectReviewOption,
} from "../lib/api";

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

/** 作れなかった理由。設定がないときは設定画面へ案内する */
type CreateError =
  { kind: "settings" } | { kind: "guest" } | { kind: "other"; message: string };

/** 選べなかった理由。過ぎた週なら、今の週を読み直すボタンを出す */
type SelectError = { kind: "closed" } | { kind: "other"; message: string };

type Props = { user: User; onOpenSettings: () => void };

/**
 * 今の週の振り返り。セリフを字幕として出し、その週の過ごし方の選択肢を並べる。
 * まだなければ、その場で作るボタンを出す。選んだ後もボタンは残し、押せば選び直せる。
 */
export default function Review({ user, onOpenSettings }: Props) {
  // undefined は読み込み中、null はまだない週
  const [review, setReview] = useState<WeeklyReviewOut | null | undefined>(
    undefined,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  // Retry で進める。同じ条件でも effect を走らせ直すため
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<CreateError | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selectError, setSelectError] = useState<SelectError | null>(null);
  // 連打よけ。disabled は描画のあとにしか効かないので、送った直後にここで止める
  const busy = useRef(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const current = await getCurrentReview(await user.getIdToken());
        if (cancelled) return;
        setReview(current);
        setLoadError(null);
      } catch (e) {
        if (!cancelled) setLoadError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, attempt]);

  function retry() {
    setLoadError(null);
    setSelectError(null);
    setReview(undefined);
    setAttempt((n) => n + 1);
  }

  async function create() {
    if (busy.current) return;
    busy.current = true;
    setCreating(true);
    setCreateError(null);
    try {
      setReview(await createReview(await user.getIdToken()));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setCreateError({ kind: "settings" });
      } else if (e instanceof ApiError && e.status === 403) {
        setCreateError({ kind: "guest" });
      } else {
        setCreateError({ kind: "other", message: errorMessage(e) });
      }
    } finally {
      busy.current = false;
      setCreating(false);
    }
  }

  async function select(reviewId: number, optionId: number) {
    if (busy.current) return;
    busy.current = true;
    setSelecting(true);
    setSelectError(null);
    try {
      setReview(
        await selectReviewOption(reviewId, optionId, await user.getIdToken()),
      );
    } catch (e) {
      // 409 は、開いている間に振り返りの週が替わったとき。読み直せば今の週が出る
      setSelectError(
        e instanceof ApiError && e.status === 409
          ? { kind: "closed" }
          : { kind: "other", message: errorMessage(e) },
      );
    } finally {
      busy.current = false;
      setSelecting(false);
    }
  }

  return (
    <section className="review" aria-labelledby="review-heading">
      <h3 id="review-heading">This week's review</h3>

      {loadError && (
        <p role="alert">
          {loadError}{" "}
          <button type="button" onClick={retry}>
            Retry
          </button>
        </p>
      )}
      {review === undefined && !loadError && <p>Loading…</p>}

      {review === null && (
        <>
          <p>No review for this week yet.</p>
          <button type="button" onClick={create} disabled={creating}>
            {creating ? "Creating…" : "Create this week's review"}
          </button>
          {createError?.kind === "settings" && (
            <p role="alert">
              Set your max and resting heart rate before creating a review.{" "}
              <button type="button" onClick={onOpenSettings}>
                Open settings
              </button>
            </p>
          )}
          {createError?.kind === "guest" && (
            <p role="alert">Guests can't create reviews.</p>
          )}
          {createError?.kind === "other" && (
            <p role="alert">{createError.message}</p>
          )}
        </>
      )}

      {review && (
        <>
          {/* 期間は振り返った週。下の質問はこれから過ごす週なので、取り違えないようラベルを付ける */}
          <p>
            Week reviewed: {review.period_start} – {review.period_end}
          </p>
          {/* 字幕。アバターと声は後から重ねる */}
          <p>{review.script}</p>
          <h4 id="review-plan-heading">How will you spend the week ahead?</h4>
          <div
            className="review-options"
            role="group"
            aria-labelledby="review-plan-heading"
          >
            {review.options.map((o) => {
              const chosen = o.selected_at !== null;
              return (
                <button
                  key={o.id}
                  type="button"
                  aria-pressed={chosen}
                  disabled={selecting}
                  onClick={() => {
                    if (!chosen) void select(review.id, o.id);
                  }}
                >
                  <strong>
                    {chosen ? "✓ " : ""}
                    {o.label}
                  </strong>
                  <br />
                  <span>{o.description}</span>
                </button>
              );
            })}
          </div>
          {selectError?.kind === "closed" && (
            <p role="alert">
              This review is from a past week.{" "}
              <button type="button" onClick={retry}>
                Load this week's review
              </button>
            </p>
          )}
          {selectError?.kind === "other" && (
            <p role="alert">{selectError.message}</p>
          )}
        </>
      )}
    </section>
  );
}
