import { act, fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { useState } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { Language, SettingsOut } from "../api";
import {
  getSettings,
  issueIngestToken,
  putLanguage,
  putSettings,
} from "../lib/api";
import { I18nProvider } from "../i18n";
import OnboardingPage, { POLL_MS } from "./OnboardingPage";

vi.mock("../lib/api", async (importOriginal) => ({
  ApiError: (await importOriginal<typeof import("../lib/api")>()).ApiError,
  getSettings: vi.fn(),
  putLanguage: vi.fn(),
  putSettings: vi.fn(),
  issueIngestToken: vi.fn(),
}));

const user = { getIdToken: async () => "token" } as unknown as User;
const onOpenDashboard = vi.fn();

/** 初めてログインした人。心拍もトークンもなく、データも届いていない */
const fresh: SettingsOut = {
  max_heart_rate: null,
  resting_heart_rate: null,
  zone_boundary_1: null,
  zone_boundary_2: null,
  timezone: "Europe/London",
  review_weekday: 3,
  send_notes_to_ai: false,
  language: "en",
  ingest_token_last_four: null,
  last_received_at: null,
};

function renderPage() {
  return render(
    <OnboardingPage user={user} onOpenDashboard={onOpenDashboard} />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSettings).mockResolvedValue(fresh);
});

afterEach(() => {
  vi.useRealTimers();
});

test("心拍を保存すると、境目は最大心拍の 80% と 90% で入り、ほかの設定は読んだまま送る", async () => {
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
    last_received_at: null,
  }));
  renderPage();

  fireEvent.change(await screen.findByLabelText("Max heart rate"), {
    target: { value: "180" },
  });
  fireEvent.change(screen.getByLabelText("Resting heart rate"), {
    target: { value: "50" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  // 読むだけの項目（トークンの末尾、最後に届いた日時）と、別の窓口で送る言語は送らない
  expect(putSettings).toHaveBeenCalledWith(
    {
      max_heart_rate: 180,
      resting_heart_rate: 50,
      zone_boundary_1: 144,
      zone_boundary_2: 162,
      timezone: "Europe/London",
      review_weekday: 3,
      send_notes_to_ai: false,
    },
    "token",
  );
  expect(
    screen.getByRole("heading", { name: /Enter your heart rate/ }),
  ).toHaveTextContent("Done");
});

test("自分で入れた境目は、最大心拍を変えても変えない", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...fresh,
    max_heart_rate: 180,
    resting_heart_rate: 50,
    zone_boundary_1: 140,
    zone_boundary_2: 160,
  });
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
    last_received_at: null,
  }));
  renderPage();

  fireEvent.change(await screen.findByLabelText("Max heart rate"), {
    target: { value: "190" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await screen.findByRole("status");
  expect(putSettings).toHaveBeenCalledWith(
    expect.objectContaining({
      max_heart_rate: 190,
      zone_boundary_1: 140,
      zone_boundary_2: 160,
    }),
    "token",
  );
});

test("範囲の外の心拍は送らずに、理由を出す", async () => {
  renderPage();

  fireEvent.change(await screen.findByLabelText("Max heart rate"), {
    target: { value: "300" },
  });
  fireEvent.change(screen.getByLabelText("Resting heart rate"), {
    target: { value: "50" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Max heart rate must be a whole number from 100 to 250.",
  );
  expect(putSettings).not.toHaveBeenCalled();
});

test("トークンを発行すると、ヘッダーの値に平文を出してコピーできる", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  vi.mocked(issueIngestToken).mockResolvedValue({
    token: "secret-wxyz",
    last_four: "wxyz",
  });
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Issue token" }));

  expect(await screen.findByText("Bearer secret-wxyz")).toBeInTheDocument();
  const copies = screen.getAllByRole("button", { name: "Copy" });
  // URL、ヘッダーのキー、ヘッダーの値の 3 つ
  expect(copies).toHaveLength(3);
  fireEvent.click(copies[2]);
  expect(writeText).toHaveBeenCalledWith("Bearer secret-wxyz");
  expect(
    await screen.findByRole("button", { name: "Copied" }),
  ).toBeInTheDocument();
});

test("発行済みのトークンは末尾だけ出し、新しく発行すると前のは使えなくなると伝える", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...fresh,
    ingest_token_last_four: "abcd",
  });
  renderPage();

  expect(
    await screen.findByText(/A token is already issued \(ends with …abcd\)/),
  ).toHaveTextContent("The old one stops working.");
  expect(
    screen.getByRole("button", { name: "Issue a new token" }),
  ).toBeInTheDocument();
  // 平文は持っていないので、値はコピーさせない
  expect(screen.getByText("Bearer <token>")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Copy" })).toHaveLength(2);
});

test("トークンがなければ、最初のデータを待たずに先の手順を案内する", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  renderPage();

  expect(
    await screen.findByText("Finish steps 2 to 4 first."),
  ).toBeInTheDocument();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_MS * 2);
  });
  expect(getSettings).toHaveBeenCalledTimes(1);
});

test("トークンがあれば数秒おきに確かめ、届いたらダッシュボードへ進める", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(getSettings)
    .mockResolvedValueOnce({ ...fresh, ingest_token_last_four: "abcd" })
    .mockResolvedValueOnce({ ...fresh, ingest_token_last_four: "abcd" })
    .mockResolvedValue({
      ...fresh,
      ingest_token_last_four: "abcd",
      last_received_at: "2026-11-17T09:00:00Z",
    });
  renderPage();

  expect(await screen.findByText(/Waiting for the first send/)).toBeVisible();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_MS);
  });
  expect(
    screen.queryByText("Your first data arrived."),
  ).not.toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_MS);
  });
  expect(screen.getByText("Your first data arrived.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Go to dashboard" }));
  expect(onOpenDashboard).toHaveBeenCalled();

  // 届いたあとは聞かない
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_MS * 2);
  });
  expect(getSettings).toHaveBeenCalledTimes(3);
});

test("あとで設定するを押すと、ダッシュボードへ移る", async () => {
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Skip for now" }));

  expect(onOpenDashboard).toHaveBeenCalled();
});

test("画面の言語が日本語なら、手順と設定の項目を日本語で出す", async () => {
  render(
    <I18nProvider language="ja" setLanguage={() => {}}>
      <OnboardingPage user={user} onOpenDashboard={onOpenDashboard} />
    </I18nProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "iPhone の設定" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("最大心拍数")).toBeInTheDocument();
  expect(screen.getByText("「VO2 Max」だけ")).toBeInTheDocument();
  expect(screen.getByText("心肺機能（VO2max）")).toBeInTheDocument();
  // 自動化は有効にして「更新」で保存しないと送られない
  expect(screen.getByText("有効化済み")).toBeInTheDocument();
  expect(
    screen.getByText(/右上の「更新」を押して保存します/),
  ).toBeInTheDocument();
});

test("心拍を入れる前でも、案内の言語を変えられる", async () => {
  vi.mocked(putLanguage).mockImplementation(async (language) => ({
    ...fresh,
    language,
  }));
  function WithLanguage() {
    const [language, setLanguage] = useState<Language>("en");
    return (
      <I18nProvider language={language} setLanguage={setLanguage}>
        <OnboardingPage user={user} onOpenDashboard={onOpenDashboard} />
      </I18nProvider>
    );
  }
  render(<WithLanguage />);

  fireEvent.change(await screen.findByLabelText("Language"), {
    target: { value: "ja" },
  });

  expect(
    await screen.findByRole("heading", { name: "iPhone の設定" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("言語")).toHaveValue("ja");
  expect(putLanguage).toHaveBeenCalledWith("ja", "token");
  expect(putSettings).not.toHaveBeenCalled();
});
