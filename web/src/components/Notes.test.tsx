import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { NoteOut } from "../api";
import { addNote, ApiError, deleteNote, editNote, getNotes } from "../lib/api";
import Notes from "./Notes";

vi.mock("../lib/api", async (importOriginal) => ({
  // ApiError は本物を使う。状態コードで出し分けるため
  ApiError: (await importOriginal<typeof import("../lib/api")>()).ApiError,
  getNotes: vi.fn(),
  addNote: vi.fn(),
  editNote: vi.fn(),
  deleteNote: vi.fn(),
}));

const user = { getIdToken: async () => "token" } as unknown as User;

function note(date: string, body: string, id = 1): NoteOut {
  return {
    id,
    date,
    body,
    label: null,
    created_at: `${date}T12:00:00Z`,
    updated_at: `${date}T12:00:00Z`,
  };
}

function renderNotes(since = "2026-09-01") {
  return render(<Notes user={user} since={since} today="2026-10-18" />);
}

/** 保存したメモが次の一覧に出る、偽の api。保存のあとに一覧を読み直すため */
let stored: NoteOut[] = [];

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  stored = [];
  vi.mocked(getNotes).mockImplementation(async ({ since }) => ({
    items: stored
      .filter((n) => !since || n.date >= since)
      .sort((a, b) => b.date.localeCompare(a.date)),
  }));
  vi.mocked(addNote).mockImplementation(async (body) => {
    const saved = note(body.date, body.body, stored.length + 1);
    stored.push(saved);
    return saved;
  });
  vi.mocked(editNote).mockImplementation(async (id, body) => {
    const found = stored.find((n) => n.id === id);
    if (!found) throw new ApiError(404);
    const saved = { ...found, body: body.body };
    stored = stored.map((n) => (n.id === id ? saved : n));
    return saved;
  });
  vi.mocked(deleteNote).mockImplementation(async (id) => {
    if (!stored.some((n) => n.id === id)) throw new ApiError(404);
    stored = stored.filter((n) => n.id !== id);
  });
});

test("期間のメモを読み、新しい日付から並べる", async () => {
  stored = [note("2026-09-20", "Sick."), note("2026-10-10", "Rest day.", 2)];
  renderNotes();

  const list = await screen.findByRole("list", {
    name: "Notes in this period",
  });
  const items = within(list).getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("2026-10-10 Rest day.");
  expect(items[1]).toHaveTextContent("2026-09-20 Sick.");
  expect(getNotes).toHaveBeenCalledWith({ since: "2026-09-01" }, "token");
});

test("日付は今日が既定で、今日より先は選べない", async () => {
  renderNotes();
  await screen.findByText("No notes in this period.");

  const date = screen.getByLabelText("Date");
  expect(date).toHaveValue("2026-10-18");
  expect(date).toHaveAttribute("max", "2026-10-18");
});

test("走らなかった日を選んで書くと、保存して一覧に足す", async () => {
  stored = [note("2026-10-10", "Rest day.")];
  renderNotes();
  await screen.findByRole("list", { name: "Notes in this period" });

  fireEvent.change(screen.getByLabelText("Date"), {
    target: { value: "2026-10-12" },
  });
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Legs heavy." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save note" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  expect(addNote).toHaveBeenCalledWith(
    { date: "2026-10-12", body: "Legs heavy." },
    "token",
  );
  const items = screen.getAllByRole("listitem");
  expect(items.map((li) => li.textContent)).toEqual([
    "2026-10-12 Legs heavy.",
    "2026-10-10 Rest day.",
  ]);
  // 書いた日は 1 日 1 件になったので、書く欄はそのメモを直す欄になる
  expect(screen.getByLabelText("Note")).toHaveValue("Legs heavy.");
  expect(
    screen.queryByRole("button", { name: "Save note" }),
  ).not.toBeInTheDocument();

  // 別の日を選ぶと、空の書く欄が開く
  fireEvent.change(screen.getByLabelText("Date"), {
    target: { value: "2026-10-13" },
  });
  expect(screen.getByLabelText("Note")).toHaveValue("");
});

test("本文が空白だけなら保存できない", async () => {
  renderNotes();
  await screen.findByText("No notes in this period.");

  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "   " },
  });

  expect(screen.getByRole("button", { name: "Save note" })).toBeDisabled();
});

test("書いてある日を選ぶと、そのメモを直す欄になる", async () => {
  stored = [note("2026-10-18", "Good ride.")];
  renderNotes();
  await screen.findByRole("list", { name: "Notes in this period" });

  expect(screen.getByLabelText("Note")).toHaveValue("Good ride.");
  expect(
    screen.queryByRole("button", { name: "Save note" }),
  ).not.toBeInTheDocument();
  // 直していないうちは保存できない
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
});

test("一覧の日付を押すと、その日を選ぶ", async () => {
  stored = [note("2026-10-10", "Rest day.")];
  renderNotes();

  fireEvent.click(await screen.findByRole("button", { name: "2026-10-10" }));

  expect(screen.getByLabelText("Date")).toHaveValue("2026-10-10");
  expect(screen.getByRole("listitem")).toHaveAttribute("aria-current", "date");
});

test("api が 409 なら、その日はもう書いてあると出す", async () => {
  vi.mocked(addNote).mockRejectedValue(new ApiError(409));
  renderNotes();
  await screen.findByText("No notes in this period.");

  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Again." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save note" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "You already wrote a note for this day.",
  );
  // 書いた本文は消さない
  expect(screen.getByLabelText("Note")).toHaveValue("Again.");
});

test("保存を連打しても api は 1 回だけ", async () => {
  const added = deferred<NoteOut>();
  vi.mocked(addNote).mockReturnValue(added.promise);
  renderNotes();
  await screen.findByText("No notes in this period.");
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Once." },
  });

  const button = screen.getByRole("button", { name: "Save note" });
  // 1 つの act にまとめ、描画（disabled）の前に 2 回目が届く形にする
  act(() => {
    button.click();
    button.click();
  });
  await act(async () => {
    added.resolve(note("2026-10-18", "Once."));
    await added.promise;
  });

  expect(addNote).toHaveBeenCalledTimes(1);
});

test("一覧の読み込みに失敗したらエラーを出す", async () => {
  vi.mocked(getNotes).mockRejectedValue(new ApiError(500));
  renderNotes();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
});

test("保存中は日付と本文を触れない", async () => {
  const added = deferred<NoteOut>();
  vi.mocked(addNote).mockReturnValue(added.promise);
  renderNotes();
  await screen.findByText("No notes in this period.");
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "First." },
  });

  fireEvent.click(screen.getByRole("button", { name: "Save note" }));

  // 保存の成功で本文を消すので、待つ間に次の本文を書かせない
  expect(screen.getByLabelText("Date")).toBeDisabled();
  expect(screen.getByLabelText("Note")).toBeDisabled();
  await act(async () => {
    added.resolve(note("2026-10-18", "First."));
    await added.promise;
  });
  expect(screen.getByLabelText("Date")).toBeEnabled();
});

test("一覧が届くまでは保存できない", async () => {
  const listed = deferred<{ items: NoteOut[] }>();
  vi.mocked(getNotes).mockReturnValue(listed.promise);
  renderNotes();

  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Too soon." },
  });

  // その日にもう書いてあるか分からないうちは送らない
  expect(screen.getByRole("button", { name: "Save note" })).toBeDisabled();
});

test("保存中に期間を切り替え、保存より前に頼んだ一覧が後から届いても、保存したメモは消えない", async () => {
  const added = deferred<NoteOut>();
  vi.mocked(addNote).mockReturnValueOnce(added.promise);
  const { rerender } = renderNotes("2026-09-01");
  await screen.findByText("No notes in this period.");
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Late." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save note" }));

  // 保存を待つ間に期間を切り替える。この一覧は保存より前の状態で、あとから届く
  const stale = deferred<{ items: NoteOut[] }>();
  vi.mocked(getNotes).mockReturnValueOnce(stale.promise);
  rerender(<Notes user={user} since="2026-09-15" today="2026-10-18" />);

  // 保存が終わる。api には保存され、読み直した一覧に出る
  await act(async () => {
    const saved = note("2026-10-18", "Late.");
    stored.push(saved);
    added.resolve(saved);
    await added.promise;
  });
  // 書いた日は直す欄になり本文が入るので、一覧の行で確かめる
  expect(await screen.findByRole("listitem")).toHaveTextContent("Late.");

  // 古い一覧が遅れて届いても、捨てる
  await act(async () => {
    stale.resolve({ items: [] });
    await stale.promise;
  });
  expect(screen.getByRole("listitem")).toHaveTextContent("Late.");
  expect(
    screen.getByRole("button", { name: "Save changes" }),
  ).toBeInTheDocument();
});

test("期間より前の日は保存できず、選べる日を案内する", async () => {
  renderNotes("2026-09-01");
  await screen.findByText("No notes in this period.");

  const date = screen.getByLabelText("Date");
  expect(date).toHaveAttribute("min", "2026-09-01");
  fireEvent.change(date, { target: { value: "2026-08-20" } });
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Old trip." },
  });

  // 書いたメモは今の期間の一覧に出るものだけにする。外に書くと 1 日 1 件の判定がずれる
  expect(screen.getByRole("button", { name: "Save note" })).toBeDisabled();
  expect(
    screen.getByText("Pick a day from 2026-09-01 to 2026-10-18."),
  ).toBeInTheDocument();
  fireEvent.submit(screen.getByRole("button", { name: "Save note" }));
  expect(addNote).not.toHaveBeenCalled();
});

test("期間を切り替えて選んでいた日が外に出たら、保存を止め、書きかけは残す", async () => {
  const { rerender } = renderNotes("2026-09-01");
  await screen.findByText("No notes in this period.");
  fireEvent.change(screen.getByLabelText("Date"), {
    target: { value: "2026-09-05" },
  });
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Draft." },
  });

  rerender(<Notes user={user} since="2026-09-15" today="2026-10-18" />);
  await screen.findByText("No notes in this period.");

  expect(screen.getByRole("button", { name: "Save note" })).toBeDisabled();
  expect(
    screen.getByText("Pick a day from 2026-09-15 to 2026-10-18."),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Note")).toHaveValue("Draft.");
});

test("一覧の読み込みに失敗しても、Retry で読み直せて、成功したらエラーを消す", async () => {
  stored = [note("2026-10-10", "Rest day.")];
  vi.mocked(getNotes).mockRejectedValueOnce(new ApiError(500));
  renderNotes();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );

  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  expect(await screen.findByText("Rest day.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(getNotes).toHaveBeenCalledTimes(2);
});

test("書いてある日の本文を直して保存すると、一覧も直り、開き直しても直ったまま", async () => {
  stored = [note("2026-10-10", "Rest day.", 7)];
  const { unmount } = renderNotes();
  fireEvent.click(await screen.findByRole("button", { name: "2026-10-10" }));

  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Rest day. Slept 9 hours." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  expect(editNote).toHaveBeenCalledWith(
    7,
    { body: "Rest day. Slept 9 hours." },
    "token",
  );
  expect(screen.getByRole("listitem")).toHaveTextContent(
    "2026-10-10 Rest day. Slept 9 hours.",
  );
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();

  unmount();
  renderNotes();
  expect(
    await screen.findByText("Rest day. Slept 9 hours."),
  ).toBeInTheDocument();
});

test("直している途中で新しく書く日に移っても、書きかけの新しい本文は残る", async () => {
  stored = [note("2026-10-10", "Rest day.")];
  renderNotes();
  await screen.findByRole("list", { name: "Notes in this period" });
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "New draft." },
  });

  fireEvent.click(screen.getByRole("button", { name: "2026-10-10" }));
  expect(screen.getByLabelText("Note")).toHaveValue("Rest day.");
  fireEvent.change(screen.getByLabelText("Date"), {
    target: { value: "2026-10-18" },
  });

  expect(screen.getByLabelText("Note")).toHaveValue("New draft.");
});

test("本文を空白だけにすると、直した保存はできない", async () => {
  stored = [note("2026-10-18", "Good ride.")];
  renderNotes();
  await screen.findByRole("list", { name: "Notes in this period" });

  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "   " },
  });

  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
});

test("確かめてから消すと、一覧から消え、その日は新しく書ける", async () => {
  stored = [note("2026-10-10", "Rest day.", 7)];
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  renderNotes();
  fireEvent.click(await screen.findByRole("button", { name: "2026-10-10" }));

  fireEvent.click(screen.getByRole("button", { name: "Delete" }));

  expect(confirm).toHaveBeenCalledWith("Delete the note for 2026-10-10?");
  expect(await screen.findByRole("status")).toHaveTextContent("Deleted");
  expect(deleteNote).toHaveBeenCalledWith(7, "token");
  expect(
    await screen.findByText("No notes in this period."),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Note")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Save note" })).toBeInTheDocument();
});

test("確かめで取り消すと、消さない", async () => {
  stored = [note("2026-10-10", "Rest day.")];
  vi.spyOn(window, "confirm").mockReturnValue(false);
  renderNotes();
  fireEvent.click(await screen.findByRole("button", { name: "2026-10-10" }));

  fireEvent.click(screen.getByRole("button", { name: "Delete" }));

  expect(deleteNote).not.toHaveBeenCalled();
  expect(screen.getByRole("listitem")).toHaveTextContent("Rest day.");
});

test("直す間は日付も本文もボタンも触れない", async () => {
  stored = [note("2026-10-18", "Good ride.")];
  const edited = deferred<NoteOut>();
  vi.mocked(editNote).mockReturnValue(edited.promise);
  renderNotes();
  await screen.findByRole("list", { name: "Notes in this period" });
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Great ride." },
  });

  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  expect(screen.getByLabelText("Date")).toBeDisabled();
  expect(screen.getByLabelText("Note")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  await act(async () => {
    edited.resolve(note("2026-10-18", "Great ride."));
    await edited.promise;
  });
  expect(screen.getByLabelText("Date")).toBeEnabled();
});

test("別の画面で消されていて 404 なら、そう出して一覧を読み直す", async () => {
  stored = [note("2026-10-18", "Good ride.")];
  renderNotes();
  await screen.findByRole("list", { name: "Notes in this period" });
  fireEvent.change(screen.getByLabelText("Note"), {
    target: { value: "Great ride." },
  });
  // 保存より前に、別の画面で消された
  stored = [];

  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This note no longer exists.",
  );
  expect(
    await screen.findByText("No notes in this period."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save note" })).toBeInTheDocument();
});
