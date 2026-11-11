import type { User } from "firebase/auth";
import { lazy, Suspense, useEffect, useRef, useState } from "react";

import type { WeeklyReviewOut } from "../api";
import AvatarBoundary from "../features/avatar/AvatarBoundary";
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
 * 再生に使う音声。振り返りとは別に持つ。選択肢を選ぶと api は同じ音声の新しい署名付き
 * URL を返すが、差し替えると再生が最初に戻るので、同じ振り返りのあいだは替えない。
 * url が null なら再生ボタンを出さない（声がない、または再生できなかった）。
 */
type Audio = {
  reviewId: number;
  url: string | null;
  // 読めなくて読み直した後。もう一度読めなければ、再生ボタンを消す
  refreshed: boolean;
  // 再生できないと決まった。選び直しで URL が返っても出し直さない
  broken: boolean;
};

/** 作るあいだに出す目安。本番の実測（Gemini、Jev、声を作るまで）で約 26 秒 */
const CREATE_HINT = "This usually takes 20–30 seconds.";

// three.js は重いので、ダッシュボードの最初の表示には含めず、あとから読む
const AvatarStage = lazy(() => import("../features/avatar/AvatarStage"));

/**
 * 今の週の振り返り。画面の右下に、アバターと吹き出しを重ねて出す（Figma の S08）。
 * 吹き出しにはセリフを字幕として出し、声があれば再生ボタンを出し、その週の
 * 過ごし方の選択肢を並べる。まだなければ、その場で作るボタンを出す。選んだ後もボタンは
 * 残し、押せば選び直せる。ゲストはデモの振り返りを見るだけ。作るボタンは出さず、
 * 選択肢は押せない。
 *
 * Hide でアバターごと畳み、Hide text で吹き出しの文字だけを隠す。どちらも外さずに隠すので、
 * 振り返りの状態もアバターのモデルも残る。
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
  const [audio, setAudio] = useState<Audio | null>(null);
  // 声を再生しているあいだ true。アバターの表情を話す顔にする
  const [speaking, setSpeaking] = useState(false);
  // false で右下の小さなボタンだけにする
  const [open, setOpen] = useState(true);
  // false で吹き出しを隠し、アバターだけにする
  const [textShown, setTextShown] = useState(true);
  const audioRef = useRef<HTMLAudioElement>(null);
  // Hide と出し直しで押したボタンが隠れるので、次に押すボタンへフォーカスを移す。
  // 最初に開いたときは動かさない
  const openRef = useRef<HTMLButtonElement>(null);
  const hideRef = useRef<HTMLButtonElement>(null);
  const focusAfterToggle = useRef(false);
  // 連打よけ。disabled は描画のあとにしか効かないので、送った直後にここで止める
  const busy = useRef(false);
  const guest = user.isAnonymous;

  // 別の振り返りになったら、その振り返りの URL で再生する。同じ振り返りでは今の URL を
  // 残す。まだ URL がなく（署名できなかった）、再生できないと決まってもいなければ、
  // 後から返った URL を使う
  if (
    review &&
    (audio?.reviewId !== review.id ||
      (audio.url === null && !audio.broken && review.audio_url !== null))
  ) {
    setAudio({
      reviewId: review.id,
      url: review.audio_url,
      refreshed: false,
      broken: false,
    });
  }
  const audioUrl = review && audio?.reviewId === review.id ? audio.url : null;

  useEffect(() => {
    if (!focusAfterToggle.current) return;
    focusAfterToggle.current = false;
    // 「– Hide」は吹き出しの末尾にあるので、そのままだと吹き出しが末尾までスクロールし、
    // 長いときは開き直すたびにセリフが見えなくなる。フォーカスだけ移し、位置は動かさない
    (open ? hideRef : openRef).current?.focus({ preventScroll: true });
  }, [open]);

  useEffect(() => {
    if (!creating) return;
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
    // 作り直したときに、前回の秒数が一瞬見えないよう、ここで 0 に戻す
    setElapsed(0);
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
   * 読み直して新しい URL にする。1 つの振り返りで 1 回だけ。読み直した URL でも読めない、
   * 読み直せない、読み直したら URL がない、のどれかなら再生ボタンを消し、字幕だけにする。
   *
   * 反映するのは音声の URL だけ。振り返りは差し替えないので、読み直しが遅れて返っても、
   * そのあいだに選んだ選択肢や、読み直した今の週を消さない。反映するのは、読み直しを
   * 始めたときと同じ振り返りの、同じ URL を再生しているときだけ
   */
  async function onAudioError(failed: Audio) {
    function update(next: Partial<Audio>) {
      setAudio((now) =>
        now?.reviewId === failed.reviewId && now.url === failed.url
          ? { ...now, ...next }
          : now,
      );
    }
    const giveUp = { url: null, broken: true };
    if (failed.refreshed) {
      update(giveUp);
      return;
    }
    let url: string | null = null;
    try {
      const fresh = await getCurrentReview(await user.getIdToken());
      url = fresh?.id === failed.reviewId ? fresh.audio_url : null;
    } catch {
      // 読み直せなければ、字幕だけにする
    }
    update(url === null ? giveUp : { url, refreshed: true });
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

  // 畳むときは声を止める。外さずに隠すので、止めないと見えないまま鳴り続ける
  function hide() {
    audioRef.current?.pause();
    setSpeaking(false);
    focusAfterToggle.current = true;
    setOpen(false);
  }

  function show() {
    focusAfterToggle.current = true;
    setOpen(true);
  }

  return (
    <div className="review-dock">
      <button
        ref={openRef}
        type="button"
        className="review-dock-open"
        hidden={open}
        onClick={show}
      >
        💬 This week's review
      </button>
      {/* 畳んでも外さずに隠す。外すと、出し直すたびにアバターのモデルを読み直す */}
      <div className="review-dock-body" hidden={!open}>
        <section
          className="review review-bubble"
          aria-labelledby="review-heading"
        >
          <h3 id="review-heading" className="visually-hidden">
            This week's review
          </h3>

          {/* 再生ボタンと Hide は一番上に置き、吹き出しをスクロールしても上端に残す。
              Figma では一番下だが、スマートフォンでは文字が長いとスクロールしないと
              見えず、真っ先に押すボタンが隠れた（iPhone の Safari で確認） */}
          <div className="review-controls">
            {/* 声を作れなかった週と、今は署名できなかったときは、字幕だけ。
                自動では鳴らさない（ブラウザが止めることが多い）。読み込むのは押してから */}
            {review && audio && audioUrl && (
              <audio
                ref={audioRef}
                className="review-audio"
                controls
                preload="none"
                src={audioUrl}
                aria-label="Listen to this review"
                onError={() => {
                  setSpeaking(false);
                  void onAudioError(audio);
                }}
                onPlay={() => setSpeaking(true)}
                onPause={() => setSpeaking(false)}
                onEnded={() => setSpeaking(false)}
                onEmptied={() => setSpeaking(false)}
              />
            )}
            <button ref={hideRef} type="button" onClick={hide}>
              – Hide
            </button>
          </div>

          {/* Hide text で隠すのは文字だけ。上の段の再生ボタンと Hide は残す */}
          <div className="review-text" hidden={!textShown}>
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
                    {creating
                      ? "Writing your review…"
                      : "Create this week's review"}
                  </button>
                )}
                {creating && (
                  <p className="muted small">
                    {CREATE_HINT} {elapsed}s
                  </p>
                )}
                {createError?.kind === "settings" && (
                  <p role="alert">
                    Set your max and resting heart rate before creating a
                    review.{" "}
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
                {/* 字幕。前後の引用符は CSS で付ける */}
                <p className="review-script">{review.script}</p>
                <h4 id="review-plan-heading">
                  How will you spend the week ahead?
                </h4>
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
                  <p>
                    Guests can't choose an option. Sign in to plan your week.
                  </p>
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
          </div>
        </section>

        <div className="review-avatar">
          {/* アバターを出せなくても、字幕と声は使えるようにする */}
          <AvatarBoundary>
            {/* 読み込むあいだも同じ大きさの枠を取り、吹き出しが動かないようにする */}
            <Suspense
              fallback={<div className="avatar-stage" aria-hidden="true" />}
            >
              <AvatarStage
                expression={review ? review.expression : "relaxed"}
                speaking={speaking && audioUrl !== null}
                visible={open}
              />
            </Suspense>
          </AvatarBoundary>
          <button
            type="button"
            className="review-text-toggle"
            onClick={() => setTextShown((shown) => !shown)}
          >
            {textShown ? "💬 Hide text" : "💬 Show text"}
          </button>
        </div>
      </div>
    </div>
  );
}
