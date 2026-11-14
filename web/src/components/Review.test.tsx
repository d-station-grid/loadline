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
      voiceLevel,
    }: {
      expression: string;
      speaking: boolean;
      visible?: boolean;
      voiceLevel?: () => number;
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
          data-voice-level={String(voiceLevel?.())}
        />
      );
    },
  };
});

const user = { getIdToken: async () => "token" } as unknown as User;

/** 3 つの選択肢を持つ週次レビュー。chosen を渡すと、その位置を選んだことにする */
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
  // 画面の大きさなど、spyOn で差し替えたものを戻す
  vi.restoreAllMocks();
});

test("今の週の週次レビューがあれば、期間とセリフと選択肢を出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();

  // 字幕は本文のまま読み上げる。aria-label で置き換えない。文ごとに分けても、
  // つなぐと元のセリフになる
  const script = (await screen.findByText(/A heavy week/)).parentElement;
  expect(script).toHaveTextContent(
    "A heavy week. Your fatigue is well above your fitness.",
  );
  expect(script).not.toHaveAttribute("aria-label");
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

test("過ぎた週の週次レビューを選ぼうとしたら、その場で今の週を読み直せる", async () => {
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

test("ゲストは週次レビューを読めるが、選択肢は押せない", async () => {
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

test("ゲストには週次レビューを作るボタンを出さない", async () => {
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

test("声があれば、Play と Replay を出す。音声は CORS つきで、押すまで読まない", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();

  expect(await screen.findByRole("button", { name: "▶ Play" })).toBeVisible();
  expect(screen.getByRole("button", { name: "↻ Replay" })).toBeVisible();
  const audio = screen.getByLabelText("Review voice");
  expect(audio).toHaveAttribute("src", AUDIO);
  // 音量を読んで口を動かすため、CORS つきで読む
  expect(audio).toHaveAttribute("crossorigin", "anonymous");
  // ブラウザ標準の再生ボタンは出さない。自動では鳴らさず、読み込むのも押してから
  expect(audio).not.toHaveAttribute("controls");
  expect(audio).not.toHaveAttribute("autoplay");
  expect(audio).toHaveAttribute("preload", "none");
});

test("Play で鳴らし、鳴っているあいだは Pause で止める。Replay は最初から", async () => {
  const play = vi
    .spyOn(HTMLMediaElement.prototype, "play")
    .mockResolvedValue(undefined);
  const pause = vi
    .spyOn(HTMLMediaElement.prototype, "pause")
    .mockImplementation(() => {});
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();

  fireEvent.click(await screen.findByRole("button", { name: "▶ Play" }));
  expect(play).toHaveBeenCalledTimes(1);

  const audio = screen.getByLabelText<HTMLAudioElement>("Review voice");
  fireEvent.play(audio);
  fireEvent.click(screen.getByRole("button", { name: "❚❚ Pause" }));
  expect(pause).toHaveBeenCalledTimes(1);
  fireEvent.pause(audio);
  expect(screen.getByRole("button", { name: "▶ Play" })).toBeInTheDocument();

  // 読み込んだあと（途中まで聞いた）なら、最初に戻す
  Object.defineProperty(audio, "readyState", { value: 4 });
  audio.currentTime = 5;
  fireEvent.click(screen.getByRole("button", { name: "↻ Replay" }));
  expect(audio.currentTime).toBe(0);
  expect(play).toHaveBeenCalledTimes(2);

  play.mockRestore();
  pause.mockRestore();
});

test("Web Audio がなくても（このテストの環境）、Play で声は鳴らせる", async () => {
  const play = vi
    .spyOn(HTMLMediaElement.prototype, "play")
    .mockResolvedValue(undefined);
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();

  expect(window.AudioContext).toBeUndefined();
  fireEvent.click(await screen.findByRole("button", { name: "▶ Play" }));

  expect(play).toHaveBeenCalledTimes(1);
  play.mockRestore();
});

test("声がなければ、字幕だけを出す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();

  expect(await screen.findByText(/A heavy week/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "▶ Play" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Review voice")).not.toBeInTheDocument();
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
  expect(await screen.findByLabelText("Review voice")).toBeInTheDocument();
  expect(screen.queryByText(/This usually takes/)).not.toBeInTheDocument();
});

const FRESH = `${AUDIO}&fresh`;

function player() {
  return screen.queryByLabelText("Review voice");
}

test("音声を読めなければ、1 回だけ読み直して新しい URL にする", async () => {
  // 署名付き URL の期限（1 時間）が切れたとき
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockResolvedValue({ ...review(), audio_url: FRESH });
  renderReview();

  fireEvent.error(await screen.findByLabelText("Review voice"));

  await waitFor(() => expect(player()).toHaveAttribute("src", FRESH));
  expect(getCurrentReview).toHaveBeenCalledTimes(2);
});

test("読み直した URL でも読めなければ CORS を外して読み、それでも読めなければ再生ボタンを消す", async () => {
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockResolvedValue({ ...review(), audio_url: FRESH });
  renderReview();
  fireEvent.error(await screen.findByLabelText("Review voice"));
  await waitFor(() => expect(player()).toHaveAttribute("src", FRESH));
  expect(player()).toHaveAttribute("crossorigin", "anonymous");

  // 新しい URL でも読めない。CORS の失敗かもしれないので、外して同じ URL を読む
  const withCors = player();
  fireEvent.error(withCors!);
  await waitFor(() => expect(player()).not.toHaveAttribute("crossorigin"));
  // 要素は作り直す（Web Audio につないだ要素は CORS を外せない）
  expect(player()).not.toBe(withCors);
  expect(player()).toHaveAttribute("src", FRESH);
  expect(screen.getByRole("button", { name: "▶ Play" })).toBeInTheDocument();

  // それでも読めなければ、字幕だけにする
  fireEvent.error(player()!);
  await waitFor(() => expect(player()).not.toBeInTheDocument());
  expect(
    screen.queryByRole("button", { name: "▶ Play" }),
  ).not.toBeInTheDocument();
  // もう読み直さない
  expect(getCurrentReview).toHaveBeenCalledTimes(2);
  expect(screen.getByText(/A heavy week/)).toBeInTheDocument();
});

test("CORS を外した声は、Web Audio につながずに鳴らす（つなぐと無音になる）", async () => {
  const sources = vi.fn(() => ({ connect() {} }));
  vi.stubGlobal(
    "AudioContext",
    class {
      destination = {};
      createAnalyser() {
        return { fftSize: 0, connect() {}, getByteTimeDomainData() {} };
      }
      createMediaElementSource = sources;
      resume() {
        return Promise.resolve();
      }
      close() {
        return Promise.resolve();
      }
    },
  );
  const play = vi
    .spyOn(HTMLMediaElement.prototype, "play")
    .mockResolvedValue(undefined);
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockResolvedValue({ ...review(), audio_url: FRESH });
  renderReview();
  fireEvent.error(await screen.findByLabelText("Review voice"));
  await waitFor(() => expect(player()).toHaveAttribute("src", FRESH));
  fireEvent.error(player()!);
  await waitFor(() => expect(player()).not.toHaveAttribute("crossorigin"));

  fireEvent.click(screen.getByRole("button", { name: "▶ Play" }));

  expect(play).toHaveBeenCalledTimes(1);
  expect(sources).not.toHaveBeenCalled();
  play.mockRestore();
  vi.unstubAllGlobals();
});

test("まだ読んでいない声の Replay は、シークせずに鳴らす", async () => {
  const play = vi
    .spyOn(HTMLMediaElement.prototype, "play")
    .mockResolvedValue(undefined);
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();
  const audio = await screen.findByLabelText<HTMLAudioElement>("Review voice");
  // 古い仕様のブラウザは、読み込む前（readyState 0）のシークで例外を出す
  const seek = vi.fn(() => {
    throw new DOMException("not loaded", "InvalidStateError");
  });
  Object.defineProperty(audio, "currentTime", { get: () => 0, set: seek });
  expect(audio.readyState).toBe(HTMLMediaElement.HAVE_NOTHING);

  fireEvent.click(screen.getByRole("button", { name: "↻ Replay" }));

  expect(seek).not.toHaveBeenCalled();
  expect(play).toHaveBeenCalledTimes(1);
  play.mockRestore();
});

test("シークで例外が出ても、Replay で鳴らす", async () => {
  const play = vi
    .spyOn(HTMLMediaElement.prototype, "play")
    .mockResolvedValue(undefined);
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();
  const audio = await screen.findByLabelText<HTMLAudioElement>("Review voice");
  Object.defineProperty(audio, "readyState", { value: 4 });
  Object.defineProperty(audio, "currentTime", {
    get: () => 3,
    set: () => {
      throw new DOMException("cannot seek", "InvalidStateError");
    },
  });

  fireEvent.click(screen.getByRole("button", { name: "↻ Replay" }));

  expect(play).toHaveBeenCalledTimes(1);
  play.mockRestore();
});

test.each([
  ["読み直せない", () => Promise.reject(new Error("offline"))],
  ["読み直したら URL がない", () => Promise.resolve(review())],
])("%sときは、再生ボタンを消す", async (_name, next) => {
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockImplementation(next);
  renderReview();

  fireEvent.error(await screen.findByLabelText("Review voice"));

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
  await screen.findByLabelText("Review voice");

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
  fireEvent.error(await screen.findByLabelText("Review voice"));
  fireEvent.click(option("Go easy"));
  await waitFor(() =>
    expect(option("Go easy")).toHaveAttribute("aria-pressed", "true"),
  );

  // 選ぶ前に読んだ、まだ選んでいない週次レビューが遅れて返る
  await act(async () => {
    slow.resolve({ ...review(), audio_url: FRESH });
  });

  expect(option("Go easy")).toHaveAttribute("aria-pressed", "true");
  expect(player()).toHaveAttribute("src", FRESH);
});

test("表示している週次レビューが替わっていたら、読み直した URL は使わない", async () => {
  const slow = deferred<WeeklyReviewOut | null>();
  const next = `${AUDIO}&next-week`;
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockReturnValueOnce(slow.promise)
    .mockResolvedValueOnce({ ...review(), id: 8, audio_url: next });
  vi.mocked(selectReviewOption).mockRejectedValue(new ApiError(409));
  renderReview();
  fireEvent.error(await screen.findByLabelText("Review voice"));
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

test("アバターは週次レビューの表情で立ち、声を流すあいだは話す顔にする", async () => {
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

  const audio = screen.getByLabelText("Review voice");
  fireEvent.play(audio);
  expect(avatar).toHaveAttribute("data-speaking", "true");
  // 口を動かすための声の大きさも渡す（まだ Web Audio につないでいないので 0）
  expect(avatar).toHaveAttribute("data-voice-level", "0");
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
  expect(screen.getByRole("button", { name: "▶ Play" })).toBeVisible();
  expect(screen.getByRole("button", { name: "– Hide" })).toBeVisible();
  expect(screen.getByTestId("avatar")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "💬 Show text" }));
  expect(script).toBeVisible();
});

test("Hide でアバターごと畳み、出し直しても週次レビューもアバターも作り直さない", async () => {
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
  // 週次レビューを読み直さず、アバター（モデル）も作り直さない
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

  const audio = await screen.findByLabelText("Review voice");
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
  expect(screen.getByLabelText("Review voice")).toBeInTheDocument();
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
  const audio = screen.getByLabelText("Review voice");
  const hide = screen.getByRole("button", { name: "– Hide" });
  // 文字が長くても、スクロールせずに押せる位置にある
  for (const control of [audio, hide]) {
    expect(
      control.compareDocumentPosition(script) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  }
});

/** 字幕で目立たせている文。なければ null */
function spokenSentence() {
  return document.querySelector(".review-spoken")?.textContent ?? null;
}

/** 声の位置と長さを決めて、timeupdate を送る */
function playAt(audio: HTMLElement, time: number, duration: number) {
  Object.defineProperty(audio, "currentTime", {
    value: time,
    configurable: true,
  });
  Object.defineProperty(audio, "duration", {
    value: duration,
    configurable: true,
  });
  fireEvent.timeUpdate(audio);
}

test("声を流すあいだは、字幕の今読んでいる文を目立たせ、鳴らし終えたら外す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();
  await screen.findByText(/A heavy week/);
  const audio = screen.getByLabelText("Review voice");
  // 鳴らす前は、どの文も目立たせない
  expect(spokenSentence()).toBeNull();

  // 「A heavy week.」は 13 文字、次の文は 41 文字。10 秒の声なら、最初の文は 2.4 秒まで
  playAt(audio, 1, 10);
  expect(spokenSentence()).toBe("A heavy week. ");
  playAt(audio, 6, 10);
  expect(spokenSentence()).toBe("Your fatigue is well above your fitness.");

  // 止めても、聞いていた文は残す
  fireEvent.pause(audio);
  expect(spokenSentence()).toBe("Your fatigue is well above your fitness.");

  playAt(audio, 10, 10);
  fireEvent.ended(audio);
  expect(spokenSentence()).toBeNull();
});

test("声を差し替えたら（読み直しなど）、目立たせていた文を外す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  renderReview();
  await screen.findByText(/A heavy week/);
  const audio = screen.getByLabelText("Review voice");
  playAt(audio, 1, 10);
  expect(spokenSentence()).not.toBeNull();

  fireEvent.emptied(audio);

  expect(spokenSentence()).toBeNull();
});

/** 吹き出しとアバターをまとめた、右下に浮かせた部品 */
function dock() {
  return document.querySelector<HTMLElement>(".review-dock")!;
}

/** 画面 1000×800 の右下に、300×400 の部品を置いたことにする */
function placeDock() {
  vi.spyOn(window, "innerWidth", "get").mockReturnValue(1000);
  vi.spyOn(window, "innerHeight", "get").mockReturnValue(800);
  vi.spyOn(dock(), "getBoundingClientRect").mockImplementation(() => {
    const m = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(
      dock().style.transform,
    );
    const x = m ? Number(m[1]) : 0;
    const y = m ? Number(m[2]) : 0;
    return DOMRect.fromRect({
      x: 684 + x,
      y: 384 + y,
      width: 300,
      height: 400,
    });
  });
}

function grip() {
  return document.querySelector<HTMLElement>(".review-avatar-grip")!;
}

function dragBy(dx: number, dy: number) {
  fireEvent.pointerDown(grip(), {
    pointerId: 1,
    button: 0,
    clientX: 900,
    clientY: 700,
  });
  fireEvent.pointerMove(grip(), {
    pointerId: 1,
    clientX: 900 + dx,
    clientY: 700 + dy,
  });
  fireEvent.pointerUp(grip(), { pointerId: 1 });
}

test("アバターをつかんで、吹き出しごと動かせる", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();
  await screen.findByText(/A heavy week/);
  placeDock();

  dragBy(-200, -100);

  expect(dock().style.transform).toBe("translate(-200px, -100px)");

  // 離したあとに動かしても、ついてこない
  fireEvent.pointerMove(grip(), { pointerId: 1, clientX: 0, clientY: 0 });
  expect(dock().style.transform).toBe("translate(-200px, -100px)");
});

test("動かしても、画面の外にははみ出さない", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();
  await screen.findByText(/A heavy week/);
  placeDock();

  // 左上へ大きく。左端と上端で止まる
  dragBy(-5000, -5000);
  expect(dock().style.transform).toBe("translate(-684px, -384px)");

  // 右下へ大きく。右端と下端で止まる（元の位置から 16px）
  dragBy(5000, 5000);
  expect(dock().style.transform).toBe("translate(16px, 16px)");
});

test("マウスの右ボタンでは動かさない", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();
  await screen.findByText(/A heavy week/);
  placeDock();

  fireEvent.pointerDown(grip(), {
    pointerId: 1,
    button: 2,
    clientX: 900,
    clientY: 700,
  });
  fireEvent.pointerMove(grip(), { pointerId: 1, clientX: 500, clientY: 500 });

  expect(dock().style.transform).toBe("");
});

test("画面が小さくなったら、はみ出さない位置へ戻す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();
  await screen.findByText(/A heavy week/);
  placeDock();
  dragBy(-600, -300);
  expect(dock().style.transform).toBe("translate(-600px, -300px)");

  // 画面が 1000→700 に縮み、部品は右下からの位置なので左へ 300 ずれる
  vi.spyOn(window, "innerWidth", "get").mockReturnValue(700);
  vi.spyOn(dock(), "getBoundingClientRect").mockImplementation(() => {
    const m = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(
      dock().style.transform,
    );
    const x = m ? Number(m[1]) : 0;
    const y = m ? Number(m[2]) : 0;
    return DOMRect.fromRect({
      x: 384 + x,
      y: 384 + y,
      width: 300,
      height: 400,
    });
  });
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });

  expect(dock().style.transform).toBe("translate(-384px, -300px)");
});

test("前の週の声を途中まで聞いてから次の週を読み込んでも、前の位置で文を目立たせない", async () => {
  const next: WeeklyReviewOut = {
    ...review(),
    id: 8,
    script: "A steady week. Keeping this rhythm is how fitness builds.",
    audio_url: `${AUDIO}&next`,
  };
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockResolvedValueOnce(next);
  vi.mocked(selectReviewOption).mockRejectedValue(new ApiError(409));
  renderReview();
  await screen.findByText(/A heavy week/);
  playAt(screen.getByLabelText("Review voice"), 6, 10);
  expect(spokenSentence()).not.toBeNull();

  fireEvent.click(option("Go easy"));
  fireEvent.click(
    await screen.findByRole("button", { name: "Load this week's review" }),
  );

  await screen.findByText(/A steady week/);
  expect(spokenSentence()).toBeNull();
});

test("読み直して同じ声が返っても、前の位置で文を目立たせない（<audio> は最初から）", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue({
    ...review(),
    audio_url: AUDIO,
  });
  vi.mocked(selectReviewOption).mockRejectedValue(new ApiError(409));
  renderReview();
  await screen.findByText(/A heavy week/);
  playAt(screen.getByLabelText("Review voice"), 6, 10);
  expect(spokenSentence()).not.toBeNull();

  fireEvent.click(option("Go easy"));
  fireEvent.click(
    await screen.findByRole("button", { name: "Load this week's review" }),
  );

  await screen.findByLabelText("Review voice");
  expect(spokenSentence()).toBeNull();
});

test("CORS を外して <audio> を作り直したら、前の位置で文を目立たせない", async () => {
  vi.mocked(getCurrentReview)
    .mockResolvedValueOnce({ ...review(), audio_url: AUDIO })
    .mockResolvedValue({ ...review(), audio_url: FRESH });
  renderReview();
  fireEvent.error(await screen.findByLabelText("Review voice"));
  await waitFor(() => expect(player()).toHaveAttribute("src", FRESH));
  playAt(player()!, 6, 10);
  expect(spokenSentence()).not.toBeNull();

  // 作り直した要素からは emptied が届かない
  fireEvent.error(player()!);
  await waitFor(() => expect(player()).not.toHaveAttribute("crossorigin"));

  expect(spokenSentence()).toBeNull();
});

test("動かしているあいだに画面が縮んでも、離したら画面に収める", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();
  await screen.findByText(/A heavy week/);
  placeDock();
  fireEvent.pointerDown(grip(), {
    pointerId: 1,
    button: 0,
    clientX: 900,
    clientY: 700,
  });
  fireEvent.pointerMove(grip(), { pointerId: 1, clientX: 300, clientY: 400 });
  expect(dock().style.transform).toBe("translate(-600px, -300px)");

  // 動かしているあいだに、画面が 1000→700 に縮む。部品は右下からの位置なので左へ 300 ずれる
  vi.spyOn(window, "innerWidth", "get").mockReturnValue(700);
  vi.spyOn(dock(), "getBoundingClientRect").mockImplementation(() => {
    const m = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(
      dock().style.transform,
    );
    const x = m ? Number(m[1]) : 0;
    const y = m ? Number(m[2]) : 0;
    return DOMRect.fromRect({
      x: 384 + x,
      y: 384 + y,
      width: 300,
      height: 400,
    });
  });
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
  fireEvent.pointerUp(grip(), { pointerId: 1 });

  expect(dock().style.transform).toBe("translate(-384px, -300px)");
});

/** Hide で畳んだあとの、出し直すボタン */
async function collapse() {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();
  await screen.findByText(/A heavy week/);
  fireEvent.click(screen.getByRole("button", { name: "– Hide" }));
  placeDock();
  return screen.getByRole("button", { name: "💬 This week's review" });
}

function isOpen() {
  return screen.queryByRole("button", { name: "– Hide" }) !== null;
}

test("畳んだあとのボタンも、つかんで動かせる。動かしたあとに離しても開かない", async () => {
  const reopen = await collapse();

  fireEvent.pointerDown(reopen, {
    pointerId: 1,
    button: 0,
    clientX: 900,
    clientY: 700,
  });
  fireEvent.pointerMove(reopen, { pointerId: 1, clientX: 700, clientY: 600 });
  fireEvent.pointerUp(reopen, { pointerId: 1 });
  fireEvent.click(reopen, { detail: 1 });

  expect(dock().style.transform).toBe("translate(-200px, -100px)");
  expect(isOpen()).toBe(false);
});

test("畳んだあとのボタンは、動かさずに押せば開く。手のぶれ程度なら動かさない", async () => {
  const reopen = await collapse();

  fireEvent.pointerDown(reopen, {
    pointerId: 1,
    button: 0,
    clientX: 900,
    clientY: 700,
  });
  fireEvent.pointerMove(reopen, { pointerId: 1, clientX: 902, clientY: 701 });
  fireEvent.pointerUp(reopen, { pointerId: 1 });
  fireEvent.click(reopen, { detail: 1 });

  expect(dock().style.transform).toBe("");
  expect(isOpen()).toBe(true);
});

test("動かしたあとでも、キーボードで押せば開く", async () => {
  const reopen = await collapse();
  // 指で動かしたあとは click が来ないことがあり、止める印が残る
  fireEvent.pointerDown(reopen, {
    pointerId: 1,
    button: 0,
    clientX: 900,
    clientY: 700,
  });
  fireEvent.pointerMove(reopen, { pointerId: 1, clientX: 700, clientY: 600 });
  fireEvent.pointerUp(reopen, { pointerId: 1 });

  // キーボードで押した click は detail が 0
  fireEvent.click(reopen, { detail: 0 });

  expect(isOpen()).toBe(true);
});

/** 畳んだあとのボタンを、指またはマウスで dx だけ動かして離し、click を送る */
function pressAndSlide(
  reopen: HTMLElement,
  pointerType: "touch" | "mouse",
  dx: number,
) {
  const down = fireEvent.pointerDown(reopen, {
    pointerId: 1,
    pointerType,
    button: 0,
    clientX: 900,
    clientY: 700,
  });
  fireEvent.pointerMove(reopen, {
    pointerId: 1,
    pointerType,
    clientX: 900 + dx,
    clientY: 700,
  });
  fireEvent.pointerUp(reopen, { pointerId: 1, pointerType });
  fireEvent.click(reopen, { detail: 1 });
  // fireEvent は preventDefault されたら false を返す
  return { defaultPrevented: !down };
}

test("指は少し滑っても（16 px 未満）、動かさずに開く", async () => {
  const reopen = await collapse();
  pressAndSlide(reopen, "touch", -12);
  expect(dock().style.transform).toBe("");
  expect(isOpen()).toBe(true);
});

test("指でも 16 px 以上動かせば、動かして開かない", async () => {
  const reopen = await collapse();
  pressAndSlide(reopen, "touch", -20);
  expect(dock().style.transform).toBe("translate(-20px, 0px)");
  expect(isOpen()).toBe(false);
});

test("マウスは 12 px でも動かしたとみなし、開かない", async () => {
  const reopen = await collapse();
  pressAndSlide(reopen, "mouse", -12);
  expect(dock().style.transform).toBe("translate(-12px, 0px)");
  expect(isOpen()).toBe(false);
});

test("指でつかんだときは preventDefault しない（タップの click を消さない）。マウスはする", async () => {
  const reopen = await collapse();
  expect(pressAndSlide(reopen, "touch", 0).defaultPrevented).toBe(false);

  fireEvent.click(screen.getByRole("button", { name: "– Hide" }));
  expect(
    pressAndSlide(
      screen.getByRole("button", { name: "💬 This week's review" }),
      "mouse",
      0,
    ).defaultPrevented,
  ).toBe(true);
});

/** スマートフォンの幅（640 px 以下）にする */
function narrowScreen() {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({ matches: query === "(max-width: 640px)" }) as MediaQueryList,
  );
}

test("スマートフォンの幅では、上下にだけ動かす", async () => {
  narrowScreen();
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();
  await screen.findByText(/A heavy week/);
  placeDock();

  dragBy(-200, -100);

  expect(dock().style.transform).toBe("translate(0px, -100px)");
  vi.unstubAllGlobals();
});

test("スマートフォンの幅では、指を左右に滑らせても動かしたとみなさず、開く", async () => {
  narrowScreen();
  const reopen = await collapse();

  pressAndSlide(reopen, "touch", -30);

  expect(dock().style.transform).toBe("");
  expect(isOpen()).toBe(true);
  vi.unstubAllGlobals();
});

test("動かしたあとにスマートフォンの幅になったら、左右を右下の置き場所に戻す", async () => {
  vi.mocked(getCurrentReview).mockResolvedValue(review());
  renderReview();
  await screen.findByText(/A heavy week/);
  placeDock();
  dragBy(-200, -100);
  expect(dock().style.transform).toBe("translate(-200px, -100px)");

  narrowScreen();
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });

  expect(dock().style.transform).toBe("translate(0px, -100px)");
  vi.unstubAllGlobals();
});
