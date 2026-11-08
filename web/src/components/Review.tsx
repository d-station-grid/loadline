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

/** 作るあいだに出す目安。本番の実測（Gemini、Jev、声を作るまで）で約 26 秒 */
const CREATE_HINT = "This usually takes 20–30 seconds.";

/**
 * 今の週の振り返り。セリフを字幕として出し、声があれば再生ボタンを出し、その週の
 * 過ごし方の選択肢を並べる。まだなければ、その場で作るボタンを出す。選んだ後もボタンは
 * 残し、押せば選び直せる。ゲストはデモの振り返りを見るだけ。作るボタンは出さず、
 * 選択肢は押せない。
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
  // 作り始めてからの秒数。待つあいだ、止まっていないことを見せる
  const [elapsed, setElapsed] = useState(0);
  // 連打よけ。disabled は描画のあとにしか効かないので、送った直後にここで止める
  const busy = useRef(false);
  // 音声の URL を読み直した振り返りの id。期限切れのときに 1 回だけ読み直す
  const audioRefreshed = useRef<number | null>(null);
  const guest = user.isAnonymous;

  useEffect(() => {
    if (!creating) return;
    setElapsed(0);
    const started = Date.now();
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [creating]);

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

  /**
   * 音声を読めなかったとき。署名付き URL の期限（1 時間）が切れたと見て、振り返りを
   * 読み直して新しい URL にする。1 つの振り返りで 1 回だけ。だめなら文字だけで見せる
   */
  async function refreshAudio(reviewId: number) {
    if (audioRefreshed.current === reviewId) return;
    audioRefreshed.current = reviewId;
    try {
      const fresh = await getCurrentReview(await user.getIdToken());
      if (fresh?.id === reviewId) setReview(fresh);
    } catch {
      // 字幕は出ているので、声が出ないだけにする
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
          {!guest && (
            <button type="button" onClick={create} disabled={creating}>
              {creating ? "Writing your review…" : "Create this week's review"}
            </button>
          )}
          {creating && (
            <p className="muted small">
              {CREATE_HINT} {elapsed}s
            </p>
          )}
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
          <p className="muted small">
            Week reviewed: {review.period_start} – {review.period_end}
          </p>
          {/* 字幕。アバターは後から重ねる */}
          <p>{review.script}</p>
          {/* 声を作れなかった週と、今は署名できなかったときは、字幕だけ。
              自動では鳴らさない（ブラウザが止めることが多い）。読み込むのは押してから */}
          {review.audio_url && (
            <audio
              className="review-audio"
              controls
              preload="none"
              src={review.audio_url}
              aria-label="Listen to this review"
              onError={() => void refreshAudio(review.id)}
            />
          )}
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
                  disabled={selecting || guest}
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
          {guest && (
            <p>Guests can't choose an option. Sign in to plan your week.</p>
          )}
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
