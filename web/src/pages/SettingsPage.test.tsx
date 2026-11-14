import { act, fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { SettingsOut } from "../api";
import {
  ApiError,
  deleteAccount,
  getSettings,
  issueIngestToken,
  putSettings,
} from "../lib/api";
import SettingsPage from "./SettingsPage";

vi.mock("../lib/api", async (importOriginal) => ({
  ApiError: (await importOriginal<typeof import("../lib/api")>()).ApiError,
  deleteAccount: vi.fn(),
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  issueIngestToken: vi.fn(),
}));

const user = { getIdToken: async () => "token" } as unknown as User;

const onDeleted = vi.fn();

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
  render(<SettingsPage user={user} onDeleted={onDeleted} />);

  expect(await screen.findByLabelText("Max heart rate")).toHaveValue(180);
  expect(screen.getByText("Current token ends with …abcd")).toBeInTheDocument();
  expect(getSettings).toHaveBeenCalledWith("token");
});

test("保存した値がブラウザの一覧になくても、その値が選ばれて出る", async () => {
  // ブラウザの Intl.supportedValuesOf("timeZone") は UTC を含まない
  vi.mocked(getSettings).mockResolvedValue({ ...defaults, timezone: "UTC" });
  render(<SettingsPage user={user} onDeleted={onDeleted} />);

  expect(await screen.findByLabelText("Time zone")).toHaveValue("UTC");
});

test("Save で入力した値を送り、Saved と出る", async () => {
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
  }));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
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
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByText("No token yet.");

  fireEvent.click(screen.getByRole("button", { name: "Issue token" }));

  expect(await screen.findByText("secret-wxyz")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Reissue token" }),
  ).toBeInTheDocument();
});

test("発行を連打しても API は 1 回だけで、発行中はボタンが無効になる", async () => {
  let resolveIssue: (t: {
    token: string;
    last_four: string;
  }) => void = () => {};
  const issue = new Promise<{ token: string; last_four: string }>((resolve) => {
    resolveIssue = resolve;
  });
  vi.mocked(issueIngestToken).mockReturnValue(issue);
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByText("No token yet.");

  const button = screen.getByRole("button", { name: "Issue token" });
  // 1 つの act にまとめ、描画（disabled）の前に 2 回目のクリックが届く形にする
  act(() => {
    button.click();
    button.click();
  });

  expect(button).toBeDisabled();

  await act(async () => {
    resolveIssue({ token: "secret-wxyz", last_four: "wxyz" });
    await issue;
  });

  expect(issueIngestToken).toHaveBeenCalledTimes(1);
  expect(screen.getByText("secret-wxyz")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reissue token" })).toBeEnabled();
});

test("api が失敗したらエラーを出す", async () => {
  vi.mocked(getSettings).mockRejectedValue(new Error("API returned 500"));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
});

test.each([
  {
    name: "境目が逆",
    fields: { zone_boundary_1: 150, zone_boundary_2: 140 },
    message: "Low / Mid boundary must be lower than Mid / High boundary.",
  },
  {
    name: "境目が同じ",
    fields: { zone_boundary_1: 150, zone_boundary_2: 150 },
    message: "Low / Mid boundary must be lower than Mid / High boundary.",
  },
  {
    name: "最大心拍が範囲の外",
    fields: { max_heart_rate: 251 },
    message: "Max heart rate must be a whole number from 100 to 250.",
  },
  {
    name: "安静時心拍が範囲の外",
    fields: { resting_heart_rate: 29 },
    message: "Resting heart rate must be a whole number from 30 to 120.",
  },
  {
    name: "境目が範囲の外",
    fields: { zone_boundary_2: 59 },
    message: "Mid / High boundary must be a whole number from 60 to 250.",
  },
  {
    name: "小数",
    fields: { max_heart_rate: 180.5 },
    message: "Max heart rate must be a whole number from 100 to 250.",
  },
  {
    name: "安静時が最大以上",
    fields: { max_heart_rate: 110, resting_heart_rate: 115 },
    message: "Resting heart rate must be lower than max heart rate.",
  },
])("$name なら送らずに分かる文言を出す", async ({ fields, message }) => {
  vi.mocked(getSettings).mockResolvedValue({ ...defaults, ...fields });
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");

  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(putSettings).not.toHaveBeenCalled();
});

test("片方だけ入っているなら比べずに送る", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...defaults,
    zone_boundary_1: 150,
  });
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
  }));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");

  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Saved");
});

test("範囲の端の値は送る", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...defaults,
    max_heart_rate: 250,
    resting_heart_rate: 30,
    zone_boundary_1: 60,
    zone_boundary_2: 250,
  });
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
  }));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");

  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Saved");
});

test("入力欄に受け付ける範囲が付いている", async () => {
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const max = await screen.findByLabelText("Max heart rate");

  expect(max).toHaveAttribute("min", "100");
  expect(max).toHaveAttribute("max", "250");
  expect(screen.getByLabelText("Resting heart rate")).toHaveAttribute(
    "min",
    "30",
  );
});

test("入力した範囲外の値でも、送らずに文言を出す", async () => {
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const max = await screen.findByLabelText("Max heart rate");

  fireEvent.change(max, { target: { value: "300" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Max heart rate must be a whole number from 100 to 250.",
  );
  expect(putSettings).not.toHaveBeenCalled();
});

test("最初のボタンでは消さず、何が消えるかと確認のボタンが出る", async () => {
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  expect(
    screen.getByText(/workouts, notes, weekly reviews/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Delete my account" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  expect(deleteAccount).not.toHaveBeenCalled();
});

test("やめると元に戻り、消さない", async () => {
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(
    screen.getByRole("button", { name: "Delete account…" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete my account" }),
  ).not.toBeInTheDocument();
  expect(deleteAccount).not.toHaveBeenCalled();
  expect(onDeleted).not.toHaveBeenCalled();
});

test("確認して消すと、連打しても API は 1 回だけで、消せたら知らせる", async () => {
  let finishDelete: () => void = () => {};
  const done = new Promise<void>((resolve) => {
    finishDelete = resolve;
  });
  vi.mocked(deleteAccount).mockReturnValue(done);
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  const button = screen.getByRole("button", { name: "Delete my account" });
  // 描画（disabled）の前に 2 回目のクリックが届く形にする
  act(() => {
    button.click();
    button.click();
  });

  expect(screen.getByRole("button", { name: "Deleting…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(onDeleted).not.toHaveBeenCalled();

  await act(async () => {
    finishDelete();
    await done;
  });

  expect(deleteAccount).toHaveBeenCalledTimes(1);
  expect(deleteAccount).toHaveBeenCalledWith("token");
  expect(onDeleted).toHaveBeenCalledTimes(1);
});

test("消せなかったら、何も消えていないと出し、もう一度押せる", async () => {
  vi.mocked(deleteAccount).mockRejectedValueOnce(new ApiError(502));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nothing was deleted. Please try again.",
  );
  expect(onDeleted).not.toHaveBeenCalled();

  vi.mocked(deleteAccount).mockResolvedValueOnce(undefined);
  const again = screen.getByRole("button", { name: "Delete my account" });
  expect(again).toBeEnabled();
  fireEvent.click(again);

  await vi.waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
  expect(deleteAccount).toHaveBeenCalledTimes(2);
});

test("ゲストは消せないと出す", async () => {
  vi.mocked(deleteAccount).mockRejectedValue(new ApiError(403));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Guests can't delete the account.",
  );
  expect(onDeleted).not.toHaveBeenCalled();
});

test("消したあとのやり直しで 401 なら、消えたものとして知らせる", async () => {
  vi.mocked(deleteAccount).mockRejectedValue(new ApiError(401));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

  await vi.waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("ID トークンの更新が user-token-expired なら、利用者は消えているので知らせる", async () => {
  const gone = {
    getIdToken: vi
      .fn()
      .mockResolvedValueOnce("token")
      .mockRejectedValue({ code: "auth/user-token-expired" }),
  } as unknown as User;
  render(<SettingsPage user={gone} onDeleted={onDeleted} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

  await vi.waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
  expect(deleteAccount).not.toHaveBeenCalled();
});

test.each([
  { name: "応答が届かない", error: new TypeError("Failed to fetch") },
  { name: "502 以外の 5xx", error: new ApiError(500) },
])(
  "$name なら、消えたか分からないと出し、もう一度押せる",
  async ({ error }) => {
    vi.mocked(deleteAccount).mockRejectedValue(error);
    render(<SettingsPage user={user} onDeleted={onDeleted} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete account…" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't confirm whether your account was deleted. Please try again.",
    );
    expect(onDeleted).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Delete my account" }),
    ).toBeEnabled();
  },
);

test.each([
  { name: "internal-error", error: { code: "auth/internal-error" } },
  { name: "too-many-requests", error: { code: "auth/too-many-requests" } },
  {
    name: "network-request-failed",
    error: { code: "auth/network-request-failed" },
  },
  { name: "user-disabled", error: { code: "auth/user-disabled" } },
  { name: "code のないエラー", error: new Error("boom") },
])(
  "ID トークンを取るときの $name は、消さずに分からないと出し、もう一度押せる",
  async ({ error }) => {
    const flaky = {
      getIdToken: vi
        .fn()
        .mockResolvedValueOnce("token")
        .mockRejectedValue(error),
    } as unknown as User;
    render(<SettingsPage user={flaky} onDeleted={onDeleted} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete account…" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't confirm whether your account was deleted. Please try again.",
    );
    expect(deleteAccount).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Delete my account" }),
    ).toBeEnabled();
  },
);

test("設定を読めなくても、削除の節は出る", async () => {
  vi.mocked(getSettings).mockRejectedValue(new Error("API returned 500"));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
  expect(
    screen.getByRole("button", { name: "Delete account…" }),
  ).toBeInTheDocument();
});

test("確認に切り替えると Cancel に、やめると最初のボタンにフォーカスが移る", async () => {
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();

  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(screen.getByRole("button", { name: "Delete account…" })).toHaveFocus();
});

test("消せなかったら、消すボタンにフォーカスが戻る", async () => {
  vi.mocked(deleteAccount).mockRejectedValue(new ApiError(502));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete account…" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

  await screen.findByRole("alert");
  expect(
    screen.getByRole("button", { name: "Delete my account" }),
  ).toHaveFocus();
});

test("ゲストは設定を見られるが、保存も発行も削除も押せない", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...defaults,
    max_heart_rate: 188,
  });
  const guest = {
    isAnonymous: true,
    getIdToken: async () => "token",
  } as unknown as User;
  render(<SettingsPage user={guest} onDeleted={onDeleted} />);

  expect(await screen.findByLabelText("Max heart rate")).toHaveValue(188);
  expect(screen.getByLabelText("Max heart rate")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Issue token" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Delete account…" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/Guests can view the demo settings/),
  ).toBeInTheDocument();
});
