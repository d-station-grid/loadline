import type { User } from "firebase/auth";
import { type SubmitEvent, useEffect, useRef, useState } from "react";

import type { NoteOut } from "../api";
import { addNote, ApiError, getNotes } from "../lib/api";

const MAX_BODY = 2000;

function errorMessage(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) {
    return "You already wrote a note for this day.";
  }
  if (e instanceof ApiError && e.status === 400) {
    return "You can't write a note for a future day.";
  }
  return e instanceof Error ? e.message : "Something went wrong";
}

/** 日付の新しい順。api と同じ並び。YYYY-MM-DD は文字列のまま比べられる。 */
function newestFirst(notes: NoteOut[]): NoteOut[] {
  return [...notes].sort((a, b) => b.date.localeCompare(a.date));
}

/** since 以降のメモ。since は読んだときの期間の始まり。 */
type NoteList = { since: string; items: NoteOut[] };

type Props = {
  user: User;
  /** 一覧に出す最初の日。ダッシュボードの期間の始まり */
  since: string;
  /** 利用者のタイムゾーンでの今日。api が決めた日をそのまま使い、端末の日付は使わない */
  today: string;
};

/** ダッシュボードの期間のメモと、日付を選んで書く欄。走らなかった日にも書ける。 */
export default function Notes({ user, since, today }: Props) {
  // どの since で読んだ一覧かを組で持つ。今の since と違う間は読み込み中として扱う
  const [list, setList] = useState<NoteList | null>(null);
  // 保存のあとに一覧を読み直すために進める
  const [reload, setReload] = useState(0);
  const [date, setDate] = useState(today);
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  // 一覧の失敗と保存の失敗は分ける。一覧は読み直しに成功したら消し、Retry で読み直せる
  const [listError, setListError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // 保存の連打よけ。disabled は描画のあとにしか効かないので、送った直後にここで止める
  const savingNow = useRef(false);

  useEffect(() => {
    // 読み直すと、前に頼んだ一覧の返事は捨てる。保存より前の一覧で上書きしないため
    let cancelled = false;
    (async () => {
      try {
        const res = await getNotes({ since }, await user.getIdToken());
        if (cancelled) return;
        setList({ since, items: res.items });
        setListError(null);
      } catch (e) {
        if (!cancelled) setListError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, since, reload]);

  const notes = list && list.since === since ? list.items : null;
  // 1 日 1 件。書いてある日を選んだら、そのメモを見せて書く欄は閉じる。
  // 一覧が届くまでは、書いてある日か分からないので保存させない
  const existing = notes?.find((n) => n.date === date) ?? null;
  // 書けるのは今の期間の日だけ。書いたメモが必ず今の一覧に出て、1 日 1 件の判定がずれないように。
  // YYYY-MM-DD は文字列のまま比べられる
  const inPeriod = date >= since && date <= today;
  const canSave =
    !saving &&
    notes !== null &&
    existing === null &&
    inPeriod &&
    body.trim() !== "";

  async function handleSave(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (savingNow.current || !canSave) return;
    savingNow.current = true;
    setSaving(true);
    setSaveError(null);
    setStatus(null);
    try {
      const note = await addNote({ date, body }, await user.getIdToken());
      // 読み直しが届くまでの間も見えるよう、手元の一覧に足しておく。
      // 保存中に期間を切り替えられたら、前の期間の一覧には足さない
      setList((prev) =>
        prev && note.date >= prev.since
          ? { ...prev, items: newestFirst([...prev.items, note]) }
          : prev,
      );
      setReload((n) => n + 1);
      // 保存中は欄を無効にしているので、ここで消すのは送った本文だけ
      setBody("");
      setStatus("Saved");
    } catch (e) {
      setSaveError(errorMessage(e));
    } finally {
      savingNow.current = false;
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="notes-heading">
      <h3 id="notes-heading">Notes</h3>
      <form onSubmit={handleSave}>
        {/* 保存中は日付も本文も触らせない。保存が終わったときに次の本文を消さないため */}
        <fieldset disabled={saving}>
          <label>
            Date
            <input
              type="date"
              value={date}
              min={since}
              max={today}
              onChange={(e) => {
                setDate(e.target.value);
                setStatus(null);
                setSaveError(null);
              }}
            />
          </label>
          {existing ? (
            <p>You already wrote a note for this day.</p>
          ) : (
            <>
              <label>
                Note
                <textarea
                  value={body}
                  maxLength={MAX_BODY}
                  rows={3}
                  placeholder="How did you feel? Anything that happened?"
                  onChange={(e) => setBody(e.target.value)}
                />
              </label>
              {/* 期間を切り替えて、選んでいた日が外に出たとき。書きかけの本文は残す */}
              {!inPeriod && (
                <p>
                  Pick a day from {since} to {today}.
                </p>
              )}
              <button type="submit" disabled={!canSave}>
                Save note
              </button>
            </>
          )}
        </fieldset>
      </form>
      {status && <p role="status">{status}</p>}
      {saveError && <p role="alert">{saveError}</p>}

      {listError && (
        <p role="alert">
          {listError}{" "}
          <button
            type="button"
            onClick={() => {
              setListError(null);
              setReload((n) => n + 1);
            }}
          >
            Retry
          </button>
        </p>
      )}
      {notes === null && !listError && <p>Loading notes…</p>}
      {notes?.length === 0 && <p>No notes in this period.</p>}
      {notes && notes.length > 0 && (
        <ul aria-label="Notes in this period">
          {notes.map((n) => (
            <li key={n.id} aria-current={n.date === date ? "date" : undefined}>
              <button type="button" onClick={() => setDate(n.date)}>
                {n.date}
              </button>{" "}
              <span style={{ whiteSpace: "pre-wrap" }}>{n.body}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
