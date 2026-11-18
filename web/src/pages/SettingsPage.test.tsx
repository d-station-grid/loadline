import { act, fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { type ReactNode, useState } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import type { Language, SettingsOut } from "../api";
import {
  ApiError,
  deleteAccount,
  getSettings,
  issueIngestToken,
  putLanguage,
  putSettings,
} from "../lib/api";
import { I18nProvider } from "../i18n";
import { resetLanguageSave } from "../lib/languageSave";
import SettingsPage from "./SettingsPage";

vi.mock("../lib/api", async (importOriginal) => ({
  ApiError: (await importOriginal<typeof import("../lib/api")>()).ApiError,
  deleteAccount: vi.fn(),
  getSettings: vi.fn(),
  putLanguage: vi.fn(),
  putSettings: vi.fn(),
  issueIngestToken: vi.fn(),
}));

/** App と同じく、言語を状態に持って画面を切り替える */
function WithLanguage({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>("en");
  return (
    <I18nProvider language={language} setLanguage={setLanguage}>
      {children}
    </I18nProvider>
  );
}

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
  language: "en",
  ingest_token_last_four: null,
};

/** 心拍の 4 つがそろった、保存できる設定 */
const complete: SettingsOut = {
  ...defaults,
  max_heart_rate: 176,
  resting_heart_rate: 50,
  zone_boundary_1: 141,
  zone_boundary_2: 158,
};

beforeEach(() => {
  vi.clearAllMocks();
  // 言語の保存の状態はアプリ全体で 1 つなので、テストごとに区切る
  resetLanguageSave();
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
  vi.mocked(getSettings).mockResolvedValue({
    ...defaults,
    last_received_at: "2026-11-17T09:00:00Z",
  });
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
  }));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const max = await screen.findByLabelText("Max heart rate");

  fireEvent.change(max, { target: { value: "185" } });
  fireEvent.change(screen.getByLabelText("Resting heart rate"), {
    target: { value: "50" },
  });
  fireEvent.change(screen.getByLabelText("Review day"), {
    target: { value: "6" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  // 送るのは設定の項目だけ。トークンの末尾 4 文字と、最後に届いた日時は含めない。
  // 言語は別の窓口で送るので、これも含めない
  const {
    ingest_token_last_four: _,
    language: _language,
    ...fields
  } = defaults;
  expect(putSettings).toHaveBeenCalledWith(
    {
      ...fields,
      max_heart_rate: 185,
      resting_heart_rate: 50,
      // 境目が空だったので、最大心拍の 80% と 90% が入る
      zone_boundary_1: 148,
      zone_boundary_2: 167,
      review_weekday: 6,
    },
    "token",
  );
});

test("境目が空なら、最大心拍を入れると 80% と 90% が入り、最大心拍に合わせて変わる", async () => {
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const max = await screen.findByLabelText("Max heart rate");
  const low = screen.getByLabelText("Low / Mid boundary");
  const high = screen.getByLabelText("Mid / High boundary");

  // 打っている途中（範囲の外）では入れない
  fireEvent.change(max, { target: { value: "17" } });
  expect(low).toHaveValue(null);
  fireEvent.change(max, { target: { value: "176" } });
  expect(low).toHaveValue(141);
  expect(high).toHaveValue(158);

  // 出した値のままなら、最大心拍を直すと出し直す。途中の値を経ても同じ
  fireEvent.change(max, { target: { value: "18" } });
  fireEvent.change(max, { target: { value: "180" } });
  expect(low).toHaveValue(144);
  expect(high).toHaveValue(162);
});

test("初期値の境目は、保存した後も最大心拍に追従する", async () => {
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
  }));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const max = await screen.findByLabelText("Max heart rate");

  fireEvent.change(max, { target: { value: "176" } });
  fireEvent.change(screen.getByLabelText("Resting heart rate"), {
    target: { value: "50" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  fireEvent.change(max, { target: { value: "180" } });

  expect(screen.getByLabelText("Low / Mid boundary")).toHaveValue(144);
  expect(screen.getByLabelText("Mid / High boundary")).toHaveValue(162);
});

test("開き直しても、保存した境目が初期値と同じなら最大心拍に追従する", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const max = await screen.findByLabelText("Max heart rate");

  fireEvent.change(max, { target: { value: "180" } });

  expect(screen.getByLabelText("Low / Mid boundary")).toHaveValue(144);
  expect(screen.getByLabelText("Mid / High boundary")).toHaveValue(162);
});

test("開いた時点で境目を埋めたら、保存するよう案内し、保存したら消す", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...complete,
    zone_boundary_1: null,
    zone_boundary_2: null,
  });
  vi.mocked(putSettings).mockImplementation(async (body) => ({
    ...body,
    ingest_token_last_four: null,
  }));
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");
  const hint = "Boundaries were filled in from your max heart rate.";

  expect(screen.getByText(hint, { exact: false })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Saved");

  expect(screen.queryByText(hint, { exact: false })).not.toBeInTheDocument();
});

test("保存した境目がそろっていれば、案内は出さない", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");

  expect(
    screen.queryByText("Boundaries were filled in", { exact: false }),
  ).not.toBeInTheDocument();
});

test("片方だけ空でも、埋めると逆順になるなら埋めずに必須と出す", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...complete,
    zone_boundary_1: 170,
    zone_boundary_2: null,
  });
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");

  expect(screen.getByLabelText("Mid / High boundary")).toHaveValue(null);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Mid / High boundary is required.",
  );
  expect(putSettings).not.toHaveBeenCalled();
});

test("自分で入れた境目は、最大心拍を変えても変わらない", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...defaults,
    max_heart_rate: 176,
    zone_boundary_1: 135,
    zone_boundary_2: 160,
  });
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const max = await screen.findByLabelText("Max heart rate");

  fireEvent.change(max, { target: { value: "180" } });

  expect(screen.getByLabelText("Low / Mid boundary")).toHaveValue(135);
  expect(screen.getByLabelText("Mid / High boundary")).toHaveValue(160);
});

test("出した境目を直したら、そのあと最大心拍を変えても変わらない", async () => {
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const max = await screen.findByLabelText("Max heart rate");
  const low = screen.getByLabelText("Low / Mid boundary");

  fireEvent.change(max, { target: { value: "176" } });
  fireEvent.change(low, { target: { value: "138" } });
  fireEvent.change(max, { target: { value: "180" } });

  expect(low).toHaveValue(138);
  expect(screen.getByLabelText("Mid / High boundary")).toHaveValue(158);
});

test("心拍が空でも、言語を選んだ時点で言語だけを保存し、画面をその言語にする", async () => {
  vi.mocked(getSettings).mockResolvedValue(defaults);
  vi.mocked(putLanguage).mockImplementation(async (language) => ({
    ...defaults,
    language,
  }));
  render(
    <WithLanguage>
      <SettingsPage user={user} onDeleted={onDeleted} />
    </WithLanguage>,
  );
  const language = await screen.findByLabelText("Language");

  expect(language).toHaveValue("en");
  fireEvent.change(language, { target: { value: "ja" } });

  expect(await screen.findByLabelText("言語")).toHaveValue("ja");
  expect(screen.getByRole("heading", { name: "設定" })).toBeInTheDocument();
  expect(putLanguage).toHaveBeenCalledWith("ja", "token");
  // 保存ボタンは押していない。心拍の検査で止まることもない
  expect(putSettings).not.toHaveBeenCalled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("言語を変えても、保存前の心拍の入力は残る", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  vi.mocked(putLanguage).mockImplementation(async (language) => ({
    ...complete,
    language,
  }));
  render(
    <WithLanguage>
      <SettingsPage user={user} onDeleted={onDeleted} />
    </WithLanguage>,
  );
  fireEvent.change(await screen.findByLabelText("Max heart rate"), {
    target: { value: "185" },
  });
  fireEvent.change(screen.getByLabelText("Language"), {
    target: { value: "ja" },
  });

  expect(await screen.findByLabelText("最大心拍数")).toHaveValue(185);
});

test("言語を保存できなければ、元の言語に戻して理由を出す", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  vi.mocked(putLanguage).mockRejectedValue(new ApiError(500));
  const setLanguage = vi.fn();
  render(
    <I18nProvider language="en" setLanguage={setLanguage}>
      <SettingsPage user={user} onDeleted={onDeleted} />
    </I18nProvider>,
  );
  const language = await screen.findByLabelText("Language");
  fireEvent.change(language, { target: { value: "ja" } });

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Couldn't change the language.",
  );
  expect(language).toHaveValue("en");
  expect(setLanguage).not.toHaveBeenCalled();
});

/** 言語の保存の返事を、テストの側で 1 つずつ返す。返すまで保存は終わらない */
function holdLanguageSaves() {
  const pending: { resolve: () => void; reject: () => void }[] = [];
  vi.mocked(putLanguage).mockImplementation(
    (language) =>
      new Promise((resolve, reject) => {
        pending.push({
          resolve: () => resolve({ ...complete, language }),
          reject: () => reject(new ApiError(500)),
        });
      }),
  );
  return {
    /** 送った言語。送った順 */
    sent: () => vi.mocked(putLanguage).mock.calls.map(([language]) => language),
    answer: (i: number) => act(async () => pending[i].resolve()),
    fail: (i: number) => act(async () => pending[i].reject()),
  };
}

test("保存中に選び直したら、終わるまで送らず、終わってから最後に選んだ言語だけを送る", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  const saves = holdLanguageSaves();
  const setLanguage = vi.fn();
  render(
    <I18nProvider language="en" setLanguage={setLanguage}>
      <SettingsPage user={user} onDeleted={onDeleted} />
    </I18nProvider>,
  );
  const language = await screen.findByLabelText("Language");
  fireEvent.change(language, { target: { value: "ja" } });
  await vi.waitFor(() => expect(saves.sent()).toEqual(["ja"]));
  fireEvent.change(language, { target: { value: "en" } });
  await act(async () => {});

  // 日本語の保存が終わるまで、英語は送らない
  expect(saves.sent()).toEqual(["ja"]);
  expect(language).toHaveValue("en");
  await saves.answer(0);
  await vi.waitFor(() => expect(saves.sent()).toEqual(["ja", "en"]));
  // 途中の日本語の返事では、画面を切り替えない
  expect(setLanguage).not.toHaveBeenCalled();
  await saves.answer(1);

  await vi.waitFor(() => expect(setLanguage).toHaveBeenCalledWith("en"));
  expect(setLanguage).not.toHaveBeenCalledWith("ja");
});

test("保存中に選び直して元の言語に戻したら、送り直さない", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  const saves = holdLanguageSaves();
  const setLanguage = vi.fn();
  render(
    <I18nProvider language="en" setLanguage={setLanguage}>
      <SettingsPage user={user} onDeleted={onDeleted} />
    </I18nProvider>,
  );
  const language = await screen.findByLabelText("Language");
  fireEvent.change(language, { target: { value: "ja" } });
  await vi.waitFor(() => expect(saves.sent()).toEqual(["ja"]));
  fireEvent.change(language, { target: { value: "en" } });
  fireEvent.change(language, { target: { value: "ja" } });
  await saves.answer(0);

  await vi.waitFor(() => expect(setLanguage).toHaveBeenCalledWith("ja"));
  expect(saves.sent()).toEqual(["ja"]);
  expect(setLanguage).toHaveBeenCalledTimes(1);
});

test("保存中に画面を閉じ、開き直して選んだ言語が、前の画面の返事で上書きされない", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  const saves = holdLanguageSaves();
  const setLanguage = vi.fn();
  const page = () => (
    <I18nProvider language="en" setLanguage={setLanguage}>
      <SettingsPage user={user} onDeleted={onDeleted} />
    </I18nProvider>
  );
  const first = render(page());
  fireEvent.change(await screen.findByLabelText("Language"), {
    target: { value: "ja" },
  });
  await vi.waitFor(() => expect(saves.sent()).toEqual(["ja"]));
  first.unmount();

  render(page());
  fireEvent.change(await screen.findByLabelText("Language"), {
    target: { value: "en" },
  });
  await act(async () => {});
  expect(saves.sent()).toEqual(["ja"]);
  await saves.answer(0);
  await vi.waitFor(() => expect(saves.sent()).toEqual(["ja", "en"]));
  await saves.answer(1);

  await vi.waitFor(() => expect(setLanguage).toHaveBeenCalledWith("en"));
  expect(setLanguage).not.toHaveBeenCalledWith("ja");
});

test("選び直した言語を保存できなければ、その前に保存できた言語にして理由を出す", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  const saves = holdLanguageSaves();
  render(
    <WithLanguage>
      <SettingsPage user={user} onDeleted={onDeleted} />
    </WithLanguage>,
  );
  const language = await screen.findByLabelText("Language");
  fireEvent.change(language, { target: { value: "ja" } });
  await vi.waitFor(() => expect(saves.sent()).toEqual(["ja"]));
  fireEvent.change(language, { target: { value: "en" } });
  await saves.answer(0);
  await vi.waitFor(() => expect(saves.sent()).toEqual(["ja", "en"]));
  await saves.fail(1);

  // 保存されているのは日本語なので、画面も日本語にする
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "言語を変更できませんでした。",
  );
  expect(screen.getByLabelText("言語")).toHaveValue("ja");
});

test("画面の言語が日本語なら、項目と曜日と検査の文言を日本語で出す", async () => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  render(
    <I18nProvider language="ja" setLanguage={() => {}}>
      <SettingsPage user={user} onDeleted={onDeleted} />
    </I18nProvider>,
  );
  const max = await screen.findByLabelText("最大心拍数");

  expect(
    screen.getByRole("option", { name: "月曜日" }) as HTMLOptionElement,
  ).toBeInTheDocument();
  fireEvent.change(max, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "最大心拍数を入力してください。",
  );
  expect(putSettings).not.toHaveBeenCalled();
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
  vi.mocked(getSettings).mockResolvedValue({ ...complete, ...fields });
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");

  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(putSettings).not.toHaveBeenCalled();
});

test.each([
  { field: "max_heart_rate", message: "Max heart rate is required." },
  { field: "resting_heart_rate", message: "Resting heart rate is required." },
  { field: "zone_boundary_2", message: "Mid / High boundary is required." },
])("$field が空なら送らない", async ({ field, message }) => {
  vi.mocked(getSettings).mockResolvedValue(complete);
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  const labels: Record<string, string> = {
    max_heart_rate: "Max heart rate",
    resting_heart_rate: "Resting heart rate",
    zone_boundary_2: "Mid / High boundary",
  };
  const input = await screen.findByLabelText(labels[field]);

  fireEvent.change(input, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(putSettings).not.toHaveBeenCalled();
});

test("最大心拍があって境目が空なら、読んだ時点で境目を埋める", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...defaults,
    max_heart_rate: 176,
  });
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");

  expect(screen.getByLabelText("Low / Mid boundary")).toHaveValue(141);
  expect(screen.getByLabelText("Mid / High boundary")).toHaveValue(158);
});

test("境目が片方だけなら、空いている方だけを埋める", async () => {
  vi.mocked(getSettings).mockResolvedValue({
    ...defaults,
    max_heart_rate: 176,
    zone_boundary_1: 150,
  });
  render(<SettingsPage user={user} onDeleted={onDeleted} />);
  await screen.findByLabelText("Max heart rate");

  expect(screen.getByLabelText("Low / Mid boundary")).toHaveValue(150);
  expect(screen.getByLabelText("Mid / High boundary")).toHaveValue(158);
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
  // フォーカスを戻すのは、理由を出した描画のあとに走る effect。遅い環境では理由が出てから
  // 少し遅れるので、戻るのを待つ
  await vi.waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Delete my account" }),
    ).toHaveFocus(),
  );
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
  expect(screen.getByLabelText("Language")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Issue token" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Delete account…" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/Guests can view the demo settings/),
  ).toBeInTheDocument();
});

test("接続の欄から導入の案内を開ける。ゲストには出さない", async () => {
  const onOpenGuide = vi.fn();
  const { unmount } = render(
    <SettingsPage
      user={user}
      onDeleted={onDeleted}
      onOpenGuide={onOpenGuide}
    />,
  );

  fireEvent.click(
    await screen.findByRole("button", { name: "Open the setup guide" }),
  );
  expect(onOpenGuide).toHaveBeenCalled();
  unmount();

  const guestUser = { ...user, isAnonymous: true } as unknown as User;
  render(
    <SettingsPage
      user={guestUser}
      onDeleted={onDeleted}
      onOpenGuide={onOpenGuide}
    />,
  );
  await screen.findByText("No token yet.");
  expect(
    screen.queryByRole("button", { name: "Open the setup guide" }),
  ).not.toBeInTheDocument();
});
