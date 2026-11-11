import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { User } from "firebase/auth";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

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

// アバターは WebGL を使うので、jsdom では描けない。受け取った表情だけを見せる部品に替える
// アバターは WebGL を使うので、jsdom では描けない。受け取ったものだけを見せる部品に替える。
// mounts は作られた回数、fail を true にすると描くときに例外を出す
const avatar = vi.hoisted(() => ({ mounts: 0, fail: false }));
vi.mock("../features/avatar/AvatarStage", async () => {
  const { useEffect } = await import("react");
  return {
    default: function FakeAvatar({
      expression,
      speaking,
      visible,
    }: {
      expression: string;
      speaking: boolean;
      visible?: boolean;
    }) {
      if (avatar.fail) throw new Error("chunk load failed");
      useEffect(() => {
        avatar.mounts += 1;
      }, []);
      return (
        <div
          data-testid="avatar"
          data-expression={expression}
          data-speaking={String(speaking)}
          data-visible={String(visible)}
        />
      );
    },
  };
});

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
    expression: "relaxed",
    created_at: "2026-10-26T00:00:00Z",
    audio_url: null,
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
    name: "How will you spend the week ahead?",
  });
  return within(group).getByRole("button", { name: new RegExp(name) });
}

beforeEach(() => {
  vi.clearAllMocks();
  avatar.mounts = 0;
  avatar.fail = false;
});

afterEach(() => {
  vi.useRealTimers();
});

test("今の週の振り返りがあれば、期間とセリフと選択肢を出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();

  // 字幕は本文のまま読み上げる。aria-label で置き換えない
  expect(
    await screen.findByText(
      "A heavy week. Your fatigue is well above your fitness.",
    ),
  ).not.toHaveAttribute("aria-label");
  // 期間は振り返った週、質問はこれから過ごす週。どちらもラベルで分かる
  expect(
    screen.getByText("Week reviewed: 2026-10-19 – 2026-10-25"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "How will you spend the week ahead?" }),
  ).toBeInTheDocument();
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

test("過ぎた週の振り返りを選ぼうとしたら、その場で今の週を読み直せる", async () => {
  const next: WeeklyReviewOut = {
    ...review(),
    id: 8,
    period_start: "2026-10-26",
    period_end: "2026-11-01",
    script: "A steady week. Keeping this rhythm is how fitness builds.",
  };
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce(review())
    .mockResolvedValueOnce(next);
  vi.mocked(selectReviewOption).mockRejectedValue(new ApiError(409));
  renderReview();
  await screen.findByText(/A heavy week/);

  fireEvent.click(option("Go easy"));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This review is from a past week.",
  );
  expect(option("Go easy")).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(
    screen.getByRole("button", { name: "Load this week's review" }),
  );

  expect(await screen.findByText(/A steady week/)).toBeInTheDocument();
  expect(
    screen.getByText("Week reviewed: 2026-10-26 – 2026-11-01"),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(getCurrentReview).toHaveBeenCalledTimes(2);
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

test("Gemini が書いている間は、ボタンを止めて書いていることを出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(null);
  let finish: (r: WeeklyReviewOut) => void = () => {};
  vi.mocked(createReview).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  renderReview();
  await screen.findByText("No review for this week yet.");

  fireEvent.click(
    screen.getByRole("button", { name: "Create this week's review" }),
  );

  const writing = await screen.findByRole("button", {
    name: "Writing your review…",
  });
  expect(writing).toBeDisabled();
  finish(review());
  expect(await screen.findByText(/A heavy week/)).toBeInTheDocument();
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

const guest = {
  isAnonymous: true,
  getIdToken: async () => "token",
} as unknown as User;

test("ゲストは振り返りを読めるが、選択肢は押せない", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  render(<Review user={guest} onOpenSettings={vi.fn()} />);

  await screen.findByText(/A heavy week/);
  for (const name of ["Rest fully", "Go easy", "Short and light"]) {
    expect(option(name)).toBeDisabled();
  }
  expect(screen.getByText(/Guests can't choose an option/)).toBeInTheDocument();
  fireEvent.click(option("Go easy"));
  expect(selectReviewOption).not.toHaveBeenCalled();
});

test("ゲストには振り返りを作るボタンを出さない", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(null);
  render(<Review user={guest} onOpenSettings={vi.fn()} />);

  expect(
    await screen.findByText("No review for this week yet."),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Create this week's review" }),
  ).not.toBeInTheDocument();
});

const AUDIO = "https://storage.example/users/1/reviews/7.wav?signed";

test("声があれば、字幕の下に再生ボタンを出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();

  const audio = await screen.findByLabelText("Listen to this review");
  expect(audio).toHaveAttribute("src", AUDIO);
  expect(audio).toHaveAttribute("controls");
  // 自動では鳴らさない。読み込むのも押してから
  expect(audio).not.toHaveAttribute("autoplay");
  expect(audio).toHaveAttribute("preload", "none");
});

test("声がなければ、字幕だけを出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();

  expect(await screen.findByText(/A heavy week/)).toBeInTheDocument();
  expect(
    screen.queryByLabelText("Listen to this review"),
  ).not.toBeInTheDocument();
});

test("作っているあいだは、目安と経った秒数を出す", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(getCurrentReview).mockResolvedValue(null);
  let finish: (r: WeeklyReviewOut) => void = () => {};
  vi.mocked(createReview).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  renderReview();
  await screen.findByText("No review for this week yet.");

  fireEvent.click(
    screen.getByRole("button", { name: "Create this week's review" }),
  );
  expect(
    await screen.findByText("This usually takes 20–30 seconds. 0s"),
  ).toBeInTheDocument();
  act(() => {
    vi.advanceTimersByTime(12_000);
  });

  expect(
    screen.getByText("This usually takes 20–30 seconds. 12s"),
  ).toBeInTheDocument();
  finish({ ...review(), audio_url: AUDIO });
  expect(
    await screen.findByLabelText("Listen to this review"),
  ).toBeInTheDocument();
  expect(screen.queryByText(/This usually takes/)).not.toBeInTheDocument();
});

const FRESH = `${AUDIO}&fresh`;

function player() {
  return screen.queryByLabelText("Listen to this review");
}

test("音声を読めなければ、1 回だけ読み直して新しい URL にする", async () => {
  // 署名付き URL の期限（1 時間）が切れたとき
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockResolvedValue({ ...review(), audio_url: FRESH });
  renderReview();

  fireEvent.error(await screen.findByLabelText("Listen to this review"));

  await waitFor(() => expect(player()).toHaveAttribute("src", FRESH));
  expect(getCurrentReview).toHaveBeenCalledTimes(2);
});

test("読み直した URL でも読めなければ、再生ボタンを消して字幕だけにする", async () => {
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockResolvedValue({ ...review(), audio_url: FRESH });
  renderReview();
  fireEvent.error(await screen.findByLabelText("Listen to this review"));
  await waitFor(() => expect(player()).toHaveAttribute("src", FRESH));

  fireEvent.error(player()!);

  await waitFor(() => expect(player()).not.toBeInTheDocument());
  // もう読み直さない
  expect(getCurrentReview).toHaveBeenCalledTimes(2);
  expect(screen.getByText(/A heavy week/)).toBeInTheDocument();
});

test.each([
  ["読み直せない", () => Promise.reject(new Error("offline"))],
  ["読み直したら URL がない", () => Promise.resolve(review())],
])("%sときは、再生ボタンを消す", async (_name, next) => {
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockImplementation(next);
  renderReview();

  fireEvent.error(await screen.findByLabelText("Listen to this review"));

  await waitFor(() => expect(player()).not.toBeInTheDocument());
  expect(screen.getByText(/A heavy week/)).toBeInTheDocument();
});

test("選択肢を選んでも、再生している URL は替えない", async () => {
  // 選択の応答は、同じ音声の新しい署名付き URL を返す。替えると再生が最初に戻る
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  vi.mocked(selectReviewOption).mockResolvedValue({
    ...review(1),
    audio_url: FRESH,
  });
  renderReview();
  await screen.findByLabelText("Listen to this review");

  fireEvent.click(option("Go easy"));

  await waitFor(() =>
    expect(option("Go easy")).toHaveAttribute("aria-pressed", "true"),
  );
  expect(player()).toHaveAttribute("src", AUDIO);
});

test("読み直しが遅れて返っても、そのあいだに選んだ選択肢を消さない", async () => {
  const slow = deferred<WeeklyReviewOut | null>();
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockReturnValueOnce(slow.promise);
  vi.mocked(selectReviewOption).mockResolvedValue({
    ...review(1),
    audio_url: FRESH,
  });
  renderReview();
  fireEvent.error(await screen.findByLabelText("Listen to this review"));
  fireEvent.click(option("Go easy"));
  await waitFor(() =>
    expect(option("Go easy")).toHaveAttribute("aria-pressed", "true"),
  );

  // 選ぶ前に読んだ、まだ選んでいない振り返りが遅れて返る
  await act(async () => {
    slow.resolve({ ...review(), audio_url: FRESH });
  });

  expect(option("Go easy")).toHaveAttribute("aria-pressed", "true");
  expect(player()).toHaveAttribute("src", FRESH);
});

test("表示している振り返りが替わっていたら、読み直した URL は使わない", async () => {
  const slow = deferred<WeeklyReviewOut | null>();
  const next = `${AUDIO}&next-week`;
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockReturnValueOnce(slow.promise)
    .mockResolvedValueOnce({ ...review(), id: 8, audio_url: next });
  vi.mocked(selectReviewOption).mockRejectedValue(new ApiError(409));
  renderReview();
  fireEvent.error(await screen.findByLabelText("Listen to this review"));
  // 開いているあいだに週が替わり、今の週を読み直す
  fireEvent.click(option("Go easy"));
  fireEvent.click(
    await screen.findByRole("button", { name: "Load this week's review" }),
  );
  await waitFor(() => expect(player()).toHaveAttribute("src", next));

  await act(async () => {
    slow.resolve({ ...review(), audio_url: FRESH });
  });

  expect(player()).toHaveAttribute("src", next);
});

test("作り直すときは、経った秒数を 0 から数える", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(getCurrentReview).mockResolvedValue(null);
  const first = deferred<WeeklyReviewOut>();
  vi.mocked(createReview)
    .mockReturnValueOnce(
      first.promise.then(() => Promise.reject(new Error("timeout"))),
    )
    .mockReturnValue(new Promise(() => {}));
  renderReview();
  await screen.findByText("No review for this week yet.");
  fireEvent.click(
    screen.getByRole("button", { name: "Create this week's review" }),
  );
  act(() => {
    vi.advanceTimersByTime(5_000);
  });
  await act(async () => {
    first.resolve(review());
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("timeout");

  fireEvent.click(
    screen.getByRole("button", { name: "Create this week's review" }),
  );

  expect(
    screen.getByText("This usually takes 20–30 seconds. 0s"),
  ).toBeInTheDocument();
});

test("アバターは振り返りの表情で立ち、声を流すあいだは話す顔にする", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    expression: "happy",
    audio_url: AUDIO,
  });
  renderReview();

  const avatar = await screen.findByTestId("avatar");
  await waitFor(() =>
    expect(avatar).toHaveAttribute("data-expression", "happy"),
  );
  expect(avatar).toHaveAttribute("data-speaking", "false");

  const audio = screen.getByLabelText("Listen to this review");
  fireEvent.play(audio);
  expect(avatar).toHaveAttribute("data-speaking", "true");
  fireEvent.pause(audio);
  expect(avatar).toHaveAttribute("data-speaking", "false");
  fireEvent.play(audio);
  fireEvent.ended(audio);
  expect(avatar).toHaveAttribute("data-speaking", "false");
});

test("Hide text で文字だけを隠し、再生ボタンと Hide とアバターは残す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();

  const script = await screen.findByText(/A heavy week/);
  fireEvent.click(screen.getByRole("button", { name: "💬 Hide text" }));

  expect(script).not.toBeVisible();
  expect(screen.getByText("Go easy")).not.toBeVisible();
  // 隠しているあいだも、声を止めたり畳んだりできる
  expect(screen.getByLabelText("Listen to this review")).toBeVisible();
  expect(screen.getByRole("button", { name: "– Hide" })).toBeVisible();
  expect(screen.getByTestId("avatar")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "💬 Show text" }));
  expect(script).toBeVisible();
});

test("Hide でアバターごと畳み、出し直しても振り返りもアバターも作り直さない", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review(1));
  renderReview();

  const script = await screen.findByText(/A heavy week/);
  await waitFor(() => expect(avatar.mounts).toBe(1));
  fireEvent.click(screen.getByRole("button", { name: "– Hide" }));

  expect(script).not.toBeVisible();
  expect(screen.getByTestId("avatar")).not.toBeVisible();
  // 隠しているあいだは描かない
  expect(screen.getByTestId("avatar")).toHaveAttribute("data-visible", "false");

  fireEvent.click(
    screen.getByRole("button", { name: "💬 This week's review" }),
  );
  expect(script).toBeVisible();
  expect(screen.getByTestId("avatar")).toHaveAttribute("data-visible", "true");
  expect(option("Go easy")).toHaveAttribute("aria-pressed", "true");
  // 振り返りを読み直さず、アバター（モデル）も作り直さない
  expect(getCurrentReview).toHaveBeenCalledTimes(1);
  expect(avatar.mounts).toBe(1);
});

test("Hide と出し直しで、次に押すボタンへフォーカスを移す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();

  await screen.findByText(/A heavy week/);
  // 最初に開いたときは動かさない
  expect(document.body).toHaveFocus();

  fireEvent.click(screen.getByRole("button", { name: "– Hide" }));
  expect(
    screen.getByRole("button", { name: "💬 This week's review" }),
  ).toHaveFocus();

  fireEvent.click(
    screen.getByRole("button", { name: "💬 This week's review" }),
  );
  expect(screen.getByRole("button", { name: "– Hide" })).toHaveFocus();
});

test("Hide を押すと、流れている声を止める", async () => {
  const pause = vi
    .spyOn(HTMLMediaElement.prototype, "pause")
    .mockImplementation(() => {});
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();

  const audio = await screen.findByLabelText("Listen to this review");
  fireEvent.play(audio);
  expect(screen.getByTestId("avatar")).toHaveAttribute("data-speaking", "true");

  fireEvent.click(screen.getByRole("button", { name: "– Hide" }));

  expect(pause).toHaveBeenCalled();
  expect(screen.getByTestId("avatar")).toHaveAttribute(
    "data-speaking",
    "false",
  );
  pause.mockRestore();
});

test("アバターを出せなくても（ファイルを取れないなど）、字幕と選択肢と声は残る", async () => {
  avatar.fail = true;
  // React が受け止めたエラーを出すので、テストの出力を汚さないよう黙らせる
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();

  expect(await screen.findByText(/A heavy week/)).toBeVisible();
  expect(option("Go easy")).toBeInTheDocument();
  expect(screen.getByLabelText("Listen to this review")).toBeInTheDocument();
  expect(screen.queryByTestId("avatar")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "💬 Hide text" }),
  ).toBeInTheDocument();
  error.mockRestore();
});

test("フォーカスを移しても、吹き出しをスクロールしない", async () => {
  const focus = vi.spyOn(HTMLElement.prototype, "focus");
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();

  await screen.findByText(/A heavy week/);
  fireEvent.click(screen.getByRole("button", { name: "– Hide" }));
  fireEvent.click(
    screen.getByRole("button", { name: "💬 This week's review" }),
  );

  expect(focus).toHaveBeenCalledTimes(2);
  for (const [options] of focus.mock.calls) {
    expect(options).toEqual({ preventScroll: true });
  }
  focus.mockRestore();
});

test("再生ボタンと Hide は、セリフより前（吹き出しの一番上）に置く", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();

  const script = await screen.findByText(/A heavy week/);
  const audio = screen.getByLabelText("Listen to this review");
  const hide = screen.getByRole("button", { name: "– Hide" });
  // 文字が長くても、スクロールせずに押せる位置にある
  for (const control of [audio, hide]) {
    expect(
      control.compareDocumentPosition(script) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  }
});
