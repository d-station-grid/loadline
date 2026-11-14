import type { User } from "firebase/auth";
import {
  type Dispatch,
  type SetStateAction,
  type SubmitEvent,
  useRef,
  useState,
} from "react";

import type { NoteOut } from "../api";
import { addNote, ApiError, deleteNote, editNote } from "../lib/api";
import { displayWidth, MAX_LABEL_WIDTH, normalizeLabel } from "../lib/label";
import type { EditDraft, EditDrafts, NoteDraft } from "../lib/noteDraft";
import { useNotes, useUpdateNotes } from "../lib/queries";

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

type Props = {
  user: User;
  /** 一覧に出す最初の日。ダッシュボードの期間の始まり */
  since: string;
  /** 利用者のタイムゾーンでの今日。api が決めた日をそのまま使い、端末の日付は使わない */
  today: string;
  /** 書きかけの本文とラベル。モーダルを閉じて Notes が外れても残るよう、親が持つ */
  draft: NoteDraft;
  onDraftChange: Dispatch<SetStateAction<NoteDraft>>;
  /** 外から日を選ぶ（チャートの日付や「+ Note」）。at が変わるたびに、その日を選び直す */
  pick?: { date: string; at: number };
};

/** ラベルの幅が上限に収まるか。半角 1、全角 2 で数える */
function labelFits(label: string): boolean {
  return displayWidth(label.trim()) <= MAX_LABEL_WIDTH;
}

/** ラベルの入力欄。文字数ではなく幅で数えるので、maxLength は使わず残りを出す */
function LabelField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const width = displayWidth(value.trim());
  return (
    <>
      <label>
        Label (optional)
        <input
          type="text"
          value={value}
          placeholder="Shown on the chart"
          aria-describedby="note-label-width"
          aria-invalid={width > MAX_LABEL_WIDTH}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>{" "}
      <small id="note-label-width">
        {width} / {MAX_LABEL_WIDTH}
        {width > MAX_LABEL_WIDTH && " (too long; full-width counts as 2)"}
      </small>
    </>
  );
}

/** 1 件の下書きを消す。保存や削除が済んだメモの分だけ */
function withoutDraft(drafts: EditDrafts, id: number): EditDrafts {
  const { [id]: _done, ...rest } = drafts;
  return rest;
}

/**
 * ダッシュボードの期間のメモと、日付を選んで書く欄。走らなかった日にも書ける。
 * 書いてある日を選ぶと、同じ欄でそのメモを直したり消したりできる。
 * ゲストは読むだけ。日付は選べるが、書く欄とボタンは押せない。
 *
 * 一覧はチャートと同じ SWR のキャッシュを見る。保存や削除のあとは、手元の一覧を先に直してから
 * 裏で読み直す。書きかけは親が持つので、モーダルを閉じて外しても、開き直せば続きから書ける。
 */
export default function Notes({
  user,
  since,
  today,
  draft: written,
  onDraftChange,
  pick,
}: Props) {
  const list = useNotes(user, since);
  const updateNotes = useUpdateNotes(user);
  const [date, setDate] = useState(pick?.date ?? today);
  // 外から選ばれた日。描画の中で前の値と比べ、変わったときだけ選び直す
  const [pickedAt, setPickedAt] = useState(pick?.at);
  if (pick && pick.at !== pickedAt) {
    setPickedAt(pick.at);
    setDate(pick.date);
  }
  // 新しく書く本文。書いてある日を選んで直している間も残しておく
  const { body, label } = written;
  const setBody = (value: string) =>
    onDraftChange((d) => ({ ...d, body: value }));
  const setLabel = (value: string) =>
    onDraftChange((d) => ({ ...d, label: value }));
  // 直している本文。そのメモの下書きがなければ、メモの本文を見せる
  const editDrafts = written.edits;
  const setEditDrafts = (change: (edits: EditDrafts) => EditDrafts) =>
    onDraftChange((d) => ({ ...d, edits: change(d.edits) }));
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  // 一覧の失敗と保存の失敗は分ける。一覧は読み直しに成功したら消え、Retry で読み直せる
  const listError = list.error ? errorMessage(list.error) : null;
  const [saveError, setSaveError] = useState<string | null>(null);
  // 保存の連打よけ。disabled は描画のあとにしか効かないので、送った直後にここで止める
  const savingNow = useRef(false);
  const guest = user.isAnonymous;

  // 期間を切り替えた直後は、その期間の一覧が届くまで読み込み中として扱う
  const notes = list.data ?? null;
  // 1 日 1 件。書いてある日を選んだら、書く欄をそのメモを直す欄に切り替える。
  // 一覧が届くまでは、書いてある日か分からないので保存させない
  const existing = notes?.find((n) => n.date === date) ?? null;
  const draft: EditDraft | null =
    existing === null
      ? null
      : (editDrafts[existing.id] ?? {
          body: existing.body,
          label: existing.label ?? "",
        });
  const editBody = draft?.body ?? "";
  const editLabel = draft?.label ?? "";
  // 書けるのは今の期間の日だけ。書いたメモが必ず今の一覧に出て、1 日 1 件の判定がずれないように。
  // YYYY-MM-DD は文字列のまま比べられる
  const inPeriod = date >= since && date <= today;
  const canSave =
    !guest &&
    !saving &&
    notes !== null &&
    existing === null &&
    inPeriod &&
    body.trim() !== "" &&
    labelFits(label);
  // 直さずに保存しても意味がないので、本文かラベルが変わったときだけ押せる
  const canSaveEdit =
    !guest &&
    !saving &&
    existing !== null &&
    editBody.trim() !== "" &&
    labelFits(editLabel) &&
    (editBody.trim() !== existing.body ||
      normalizeLabel(editLabel) !== existing.label);

  /** 直している本文かラベルを書き換える */
  function changeDraft(change: Partial<EditDraft>) {
    if (!existing || !draft) return;
    const id = existing.id;
    const base = draft;
    setEditDrafts((d) => ({ ...d, [id]: { ...(d[id] ?? base), ...change } }));
  }

  /** 保存・削除の共通の手順。連打を止める */
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
      if (e instanceof ApiError && e.status === 404) void updateNotes(since);
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

  /** 読んだ期間の一覧のメモを差し替え（next が null なら外し）、裏で読み直す */
  function replaceInList(listSince: string, id: number, next: NoteOut | null) {
    return updateNotes(listSince, (items) =>
      items.flatMap((n) => (n.id !== id ? [n] : next ? [next] : [])),
    );
  }

  async function handleSave(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (existing) {
      if (!canSaveEdit) return;
      const target = existing;
      const listSince = since;
      await run(async () => {
        const note = await editNote(
          target.id,
          { body: editBody, label: normalizeLabel(editLabel) },
          await user.getIdToken(),
        );
        await replaceInList(listSince, target.id, note);
        setEditDrafts((d) => withoutDraft(d, target.id));
        return "Saved";
      });
      return;
    }
    if (!canSave) return;
    const listSince = since;
    await run(async () => {
      const note = await addNote(
        { date, body, label: normalizeLabel(label) },
        await user.getIdToken(),
      );
      // 読み直しが届くまでの間も見えるよう、書いたときの期間の一覧に足しておく。
      // 保存中に期間を切り替えられても、足すのはその期間の一覧だけ
      await updateNotes(listSince, (items) => newestFirst([...items, note]));
      // 保存中は欄を無効にしているので、ここで消すのは送った本文だけ
      setBody("");
      setLabel("");
      return "Saved";
    });
  }

  async function handleDelete() {
    if (!existing || saving) return;
    const target = existing;
    const listSince = since;
    if (!window.confirm(`Delete the note for ${target.date}?`)) return;
    await run(async () => {
      await deleteNote(target.id, await user.getIdToken());
      // 消した日は空くので、書く欄に戻る
      await replaceInList(listSince, target.id, null);
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
          {guest && <p>Guests can read the notes but can't write them.</p>}
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
          {/* ゲストは日付を選んで読めるが、書く欄とボタンは止める */}
          <fieldset disabled={guest} className="plain">
            {existing ? (
              <>
                <label>
                  Note
                  <textarea
                    value={editBody}
                    maxLength={MAX_BODY}
                    rows={3}
                    onChange={(e) => changeDraft({ body: e.target.value })}
                  />
                </label>
                <LabelField
                  value={editLabel}
                  onChange={(value) => changeDraft({ label: value })}
                />
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
                <LabelField value={label} onChange={setLabel} />
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
        </fieldset>
      </form>
      {status && <p role="status">{status}</p>}
      {saveError && <p role="alert">{saveError}</p>}

      {listError && (
        <p role="alert">
          {listError}{" "}
          <button type="button" onClick={() => void list.mutate()}>
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
              {n.label && (
                <>
                  <strong>[{n.label}]</strong>{" "}
                </>
              )}
              <span style={{ whiteSpace: "pre-wrap" }}>{n.body}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
