import type { User } from "firebase/auth";
import { type SubmitEvent, useEffect, useRef, useState } from "react";

import type { NoteOut } from "../api";
import { addNote, ApiError, deleteNote, editNote, getNotes } from "../lib/api";

const MAX_BODY = 2000;

function errorMessage(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) {
    return "You already wrote a note for this day.";
  }
  if (e instanceof ApiError && e.status === 404) {
    return "This note no longer exists.";
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

/** 直している途中の本文。メモの id ごとに持ち、別のメモへ移っても残す */
type EditDrafts = Record<number, string>;

/** 1 件の下書きを消す。保存や削除が済んだメモの分だけ */
function withoutDraft(drafts: EditDrafts, id: number): EditDrafts {
  const { [id]: _done, ...rest } = drafts;
  return rest;
}

/**
 * ダッシュボードの期間のメモと、日付を選んで書く欄。走らなかった日にも書ける。
 * 書いてある日を選ぶと、同じ欄でそのメモを直したり消したりできる。
 */
export default function Notes({ user, since, today }: Props) {
  // どの since で読んだ一覧かを組で持つ。今の since と違う間は読み込み中として扱う
  const [list, setList] = useState<NoteList | null>(null);
  // 保存のあとに一覧を読み直すために進める
  const [reload, setReload] = useState(0);
  const [date, setDate] = useState(today);
  // 新しく書く本文。書いてある日を選んで直している間も残しておく
  const [body, setBody] = useState("");
  // 直している本文。そのメモの下書きがなければ、メモの本文を見せる
  const [editDrafts, setEditDrafts] = useState<EditDrafts>({});
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
  // 1 日 1 件。書いてある日を選んだら、書く欄をそのメモを直す欄に切り替える。
  // 一覧が届くまでは、書いてある日か分からないので保存させない
  const existing = notes?.find((n) => n.date === date) ?? null;
  const editBody =
    existing === null ? "" : (editDrafts[existing.id] ?? existing.body);
  // 書けるのは今の期間の日だけ。書いたメモが必ず今の一覧に出て、1 日 1 件の判定がずれないように。
  // YYYY-MM-DD は文字列のまま比べられる
  const inPeriod = date >= since && date <= today;
  const canSave =
    !saving &&
    notes !== null &&
    existing === null &&
    inPeriod &&
    body.trim() !== "";
  // 直さずに保存しても意味がないので、本文が変わったときだけ押せる
  const canSaveEdit =
    !saving &&
    existing !== null &&
    editBody.trim() !== "" &&
    editBody.trim() !== existing.body;

  /** 保存・削除の共通の手順。連打を止め、終わったら一覧を読み直す */
  async function run(action: () => Promise<string>) {
    if (savingNow.current) return;
    savingNow.current = true;
    setSaving(true);
    setSaveError(null);
    setStatus(null);
    try {
      setStatus(await action());
    } catch (e) {
      setSaveError(errorMessage(e));
      // 別の画面で消されていたときは、一覧を読み直して書く欄に戻す
      if (e instanceof ApiError && e.status === 404) setReload((n) => n + 1);
    } finally {
      savingNow.current = false;
      setSaving(false);
    }
  }

  /** 日を選ぶ。日付欄と一覧の日付ボタンで同じ。前の日の保存の文言は消す */
  function selectDay(day: string) {
    setDate(day);
    setStatus(null);
    setSaveError(null);
  }

  /** 手元の一覧のメモを差し替える。読み直しが届くまでの間も見えるように */
  function replaceInList(id: number, next: NoteOut | null) {
    setList((prev) =>
      prev
        ? {
            ...prev,
            items: prev.items.flatMap((n) =>
              n.id !== id ? [n] : next ? [next] : [],
            ),
          }
        : prev,
    );
  }

  async function handleSave(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (existing) {
      if (!canSaveEdit) return;
      const target = existing;
      await run(async () => {
        const note = await editNote(
          target.id,
          { body: editBody },
          await user.getIdToken(),
        );
        replaceInList(target.id, note);
        setReload((n) => n + 1);
        setEditDrafts((d) => withoutDraft(d, target.id));
        return "Saved";
      });
      return;
    }
    if (!canSave) return;
    await run(async () => {
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
      return "Saved";
    });
  }

  async function handleDelete() {
    if (!existing || saving) return;
    const target = existing;
    if (!window.confirm(`Delete the note for ${target.date}?`)) return;
    await run(async () => {
      await deleteNote(target.id, await user.getIdToken());
      // 消した日は空くので、書く欄に戻る
      replaceInList(target.id, null);
      setReload((n) => n + 1);
      // 消したメモの下書きだけ消す。ほかのメモの書きかけは残す
      setEditDrafts((d) => withoutDraft(d, target.id));
      return "Deleted";
    });
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
              onChange={(e) => selectDay(e.target.value)}
            />
          </label>
          {existing ? (
            <>
              <label>
                Note
                <textarea
                  value={editBody}
                  maxLength={MAX_BODY}
                  rows={3}
                  onChange={(e) =>
                    setEditDrafts((d) => ({
                      ...d,
                      [existing.id]: e.target.value,
                    }))
                  }
                />
              </label>
              <button type="submit" disabled={!canSaveEdit}>
                Save changes
              </button>{" "}
              <button type="button" onClick={handleDelete}>
                Delete
              </button>
            </>
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
              {/* 一覧は保存中に止める fieldset の外にあるので、ここでも止める */}
              <button
                type="button"
                disabled={saving}
                onClick={() => selectDay(n.date)}
              >
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
