import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { NoteOut } from "../api";
import { addNote, ApiError, getNotes } from "../lib/api";
import Notes from "./Notes";

vi.mock("../lib/api", async (importOriginal) => ({
  // ApiError は本物を使う。状態コードで出し分けるため
  ApiError: (await importOriginal<typeof import("../lib/api")>()).ApiError,
  getNotes: vi.fn(),
  addNote: vi.fn(),
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

function renderNotes() {
  return render(<Notes user={user} since="2026-09-01" today="2026-10-18" />);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getNotes).mockResolvedValue({ items: [] });
});

test("期間のメモを読み、新しい日付から並べる", async () => {
  vi.mocked(getNotes).mockResolvedValue({
    items: [note("2026-10-10", "Rest day.", 2), note("2026-09-20", "Sick.")],
  });
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
  vi.mocked(getNotes).mockResolvedValue({
    items: [note("2026-10-10", "Rest day.", 2)],
  });
  vi.mocked(addNote).mockImplementation(async (body) =>
    note(body.date, body.body, 3),
  );
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
  // 書いた日は 1 日 1 件になったので、書く欄を閉じる
  expect(screen.queryByLabelText("Note")).not.toBeInTheDocument();

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

test("書いてある日を選ぶと、書く欄を閉じる", async () => {
  vi.mocked(getNotes).mockResolvedValue({
    items: [note("2026-10-18", "Good ride.")],
  });
  renderNotes();
  await screen.findByRole("list", { name: "Notes in this period" });

  expect(
    screen.getByText("You already wrote a note for this day."),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Note")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Save note" }),
  ).not.toBeInTheDocument();
});

test("一覧の日付を押すと、その日を選ぶ", async () => {
  vi.mocked(getNotes).mockResolvedValue({
    items: [note("2026-10-10", "Rest day.")],
  });
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
  let resolveAdd: (n: NoteOut) => void = () => {};
  const added = new Promise<NoteOut>((resolve) => {
    resolveAdd = resolve;
  });
  vi.mocked(addNote).mockReturnValue(added);
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
    resolveAdd(note("2026-10-18", "Once."));
    await added;
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
