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

type Props = {
  user: User;
  /** 一覧に出す最初の日。ダッシュボードの期間の始まり */
  since: string;
  /** 利用者のタイムゾーンでの今日。api が決めた日をそのまま使い、端末の日付は使わない */
  today: string;
};

/** ダッシュボードの期間のメモと、日付を選んで書く欄。走らなかった日にも書ける。 */
export default function Notes({ user, since, today }: Props) {
  const [notes, setNotes] = useState<NoteOut[] | null>(null);
  const [date, setDate] = useState(today);
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 保存の連打よけ。disabled は描画のあとにしか効かないので、送った直後にここで止める
  const savingNow = useRef(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await getNotes({ since }, await user.getIdToken());
        if (!cancelled) setNotes(list.items);
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, since]);

  // 1 日 1 件。書いてある日を選んだら、そのメモを見せて書く欄は閉じる
  const existing = notes?.find((n) => n.date === date) ?? null;
  const canSave =
    !saving && existing === null && date !== "" && body.trim() !== "";

  async function handleSave(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (savingNow.current || !canSave) return;
    savingNow.current = true;
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const note = await addNote({ date, body }, await user.getIdToken());
      setNotes((prev) => newestFirst([...(prev ?? []), note]));
      setBody("");
      setStatus("Saved");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      savingNow.current = false;
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="notes-heading">
      <h3 id="notes-heading">Notes</h3>
      <form onSubmit={handleSave}>
        <label>
          Date
          <input
            type="date"
            value={date}
            max={today}
            onChange={(e) => {
              setDate(e.target.value);
              setStatus(null);
              setError(null);
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
            <button type="submit" disabled={!canSave}>
              Save note
            </button>
          </>
        )}
      </form>
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}

      {notes === null && !error && <p>Loading notes…</p>}
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
