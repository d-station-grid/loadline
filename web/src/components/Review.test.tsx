import { fireEvent, render, screen, within } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { WeeklyReviewOut } from "../api";
import {
  ApiError,
  createReview,
  getCurrentReview,
  selectReviewOption,
} from "../lib/api";
import Review from "./Review";

vi.mock("../lib/api", async (importOriginal) => ({
  // ApiError は本物を使う。状態コードで出し分けるため
  ApiError: (await importOriginal<typeof import("../lib/api")>()).ApiError,
  getCurrentReview: vi.fn(),
  createReview: vi.fn(),
  selectReviewOption: vi.fn(),
}));

const user = { getIdToken: async () => "token" } as unknown as User;

/** 3 つの選択肢を持つ振り返り。chosen を渡すと、その位置を選んだことにする */
function review(chosen: number | null = null): WeeklyReviewOut {
  const options = [
    ["Rest fully", "Take a few days off to recover."],
    ["Go easy", "Only easy sessions this week."],
    ["Short and light", "Keep sessions short and the effort low."],
  ] as const;
  return {
    id: 7,
    period_start: "2026-10-19",
    period_end: "2026-10-25",
    situation: "fatigued",
    script: "A heavy week. Your fatigue is well above your fitness.",
    status: "completed",
    is_fallback: true,
    created_at: "2026-10-26T00:00:00Z",
    options: options.map(([label, description], i) => ({
      id: 100 + i,
      position: i,
      label,
      description,
      selected_at: i === chosen ? "2026-10-26T01:00:00Z" : null,
    })),
  };
}

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function renderReview() {
  const onOpenSettings = vi.fn();
  render(<Review user={user} onOpenSettings={onOpenSettings} />);
  return { onOpenSettings };
}

function option(name: string) {
  const group = screen.getByRole("group", {
    name: "How will you spend this week?",
  });
  return within(group).getByRole("button", { name: new RegExp(name) });
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("今の週の振り返りがあれば、期間とセリフと選択肢を出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();

  expect(
    await screen.findByText(
      "A heavy week. Your fatigue is well above your fitness.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("2026-10-19 – 2026-10-25")).toBeInTheDocument();
  for (const name of ["Rest fully", "Go easy", "Short and light"]) {
    expect(option(name)).toHaveAttribute("aria-pressed", "false");
  }
  expect(option("Go easy")).toHaveTextContent("Only easy sessions this week.");
});

test("選んである選択肢に印を付ける", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review(2));
  renderReview();

  await screen.findByText(/A heavy week/);
  expect(option("Short and light")).toHaveAttribute("aria-pressed", "true");
  expect(option("Short and light")).toHaveTextContent("✓ Short and light");
  expect(option("Rest fully")).toHaveAttribute("aria-pressed", "false");
});

test("選ぶと保存し、選び直すと印が移る", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  vi.mocked(selectReviewOption)
    .mockResolvedValueOnce(review(1))
    .mockResolvedValueOnce(review(0));
  renderReview();
  await screen.findByText(/A heavy week/);

  fireEvent.click(option("Go easy"));
  await vi.waitFor(() =>
    expect(option("Go easy")).toHaveAttribute("aria-pressed", "true"),
  );
  expect(selectReviewOption).toHaveBeenLastCalledWith(7, 101, "token");

  fireEvent.click(option("Rest fully"));
  await vi.waitFor(() =>
    expect(option("Rest fully")).toHaveAttribute("aria-pressed", "true"),
  );
  expect(option("Go easy")).toHaveAttribute("aria-pressed", "false");
  expect(selectReviewOption).toHaveBeenLastCalledWith(7, 100, "token");
});

test("選んである選択肢をもう一度押しても送らない", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review(1));
  renderReview();
  await screen.findByText(/A heavy week/);

  fireEvent.click(option("Go easy"));

  expect(selectReviewOption).not.toHaveBeenCalled();
});

test("保存中はボタンを止め、連打しても 1 回だけ送る", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  const pending = deferred<WeeklyReviewOut>();
  vi.mocked(selectReviewOption).mockReturnValue(pending.promise);
  renderReview();
  await screen.findByText(/A heavy week/);

  fireEvent.click(option("Go easy"));
  fireEvent.click(option("Rest fully"));
  await vi.waitFor(() => expect(option("Rest fully")).toBeDisabled());
  expect(selectReviewOption).toHaveBeenCalledTimes(1);

  pending.resolve(review(1));
  await vi.waitFor(() => expect(option("Rest fully")).toBeEnabled());
});

test("過ぎた週の振り返りを選ぼうとしたら、読み直すよう案内する", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  vi.mocked(selectReviewOption).mockRejectedValue(new ApiError(409));
  renderReview();
  await screen.findByText(/A heavy week/);

  fireEvent.click(option("Go easy"));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This review is from a past week.",
  );
  expect(option("Go easy")).toHaveAttribute("aria-pressed", "false");
});

test("まだない週は作るボタンを出し、押すとその場に出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(null);
  vi.mocked(createReview).mockResolvedValue(review());
  renderReview();

  expect(
    await screen.findByText("No review for this week yet."),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Create this week's review" }),
  );

  expect(await screen.findByText(/A heavy week/)).toBeInTheDocument();
  expect(createReview).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("button", { name: "Create this week's review" }),
  ).not.toBeInTheDocument();
});

test("心拍の設定がなくて作れなければ、設定画面へ案内する", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(null);
  vi.mocked(createReview).mockRejectedValue(new ApiError(409));
  const { onOpenSettings } = renderReview();
  await screen.findByText("No review for this week yet.");

  fireEvent.click(
    screen.getByRole("button", { name: "Create this week's review" }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Set your max and resting heart rate",
  );
  fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
  expect(onOpenSettings).toHaveBeenCalledTimes(1);
});

test("ゲストは作れないと出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(null);
  vi.mocked(createReview).mockRejectedValue(new ApiError(403));
  renderReview();
  await screen.findByText("No review for this week yet.");

  fireEvent.click(
    screen.getByRole("button", { name: "Create this week's review" }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Guests can't create reviews.",
  );
});

test("読み込みに失敗したら Retry で読み直す", async () => {
  vi.mocked(getCurrentReview)
    .mockRejectedValueOnce(new ApiError(500))
    .mockResolvedValueOnce(review());
  renderReview();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  expect(await screen.findByText(/A heavy week/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
