import { fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { SettingsOut } from "../api";
import { getSettings, issueIngestToken, putSettings } from "../lib/api";
import SettingsPage from "./SettingsPage";

vi.mock("../lib/api", () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  issueIngestToken: vi.fn(),
}));

const user = { getIdToken: async () => "token" } as unknown as User;

const defaults: SettingsOut = {
  max_heart_rate: null,
  resting_heart_rate: null,
  zone_boundary_1: null,
  zone_boundary_2: null,
  timezone: "Asia/Tokyo",
  review_weekday: 0,
  send_notes_to_ai: true,
  ingest_token_last_four: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSettings).mockResolvedValue(defaults);
});

test("読み込んだ設定がフォームに入る", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...defaults,
    max_heart_rate: 180,
    ingest_token_last_four: "abcd",
  });
  render(<SettingsPage user={user} />);

  expect(await screen.findByLabelText("Max heart rate")).toHaveValue(180);
  expect(screen.getByText("Current token ends with …abcd")).toBeInTheDocument();
  expect(getSettings).toHaveBeenCalledWith("token");
});

test("Save で入力した値を送り、Saved と出る", async () => {
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
  }));
  render(<SettingsPage user={user} />);
  const max = await screen.findByLabelText("Max heart rate");

  fireEvent.change(max, { target: { value: "185" } });
  fireEvent.change(screen.getByLabelText("Review day"), {
    target: { value: "6" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  // 送るのは設定の項目だけ。トークンの末尾 4 文字は含めない
  const { ingest_token_last_four: _, ...fields } = defaults;
  expect(putSettings).toHaveBeenCalledWith(
    { ...fields, max_heart_rate: 185, review_weekday: 6 },
    "token",
  );
});

test("トークンを発行すると平文が 1 回出る", async () => {
  vi.mocked(issueIngestToken).mockResolvedValue({
    token: "secret-wxyz",
    last_four: "wxyz",
  });
  render(<SettingsPage user={user} />);
  await screen.findByText("No token yet.");

  fireEvent.click(screen.getByRole("button", { name: "Issue token" }));

  expect(await screen.findByText("secret-wxyz")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Reissue token" }),
  ).toBeInTheDocument();
});

test("api が失敗したらエラーを出す", async () => {
  vi.mocked(getSettings).mockRejectedValue(new Error("API returned 500"));
  render(<SettingsPage user={user} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
});
