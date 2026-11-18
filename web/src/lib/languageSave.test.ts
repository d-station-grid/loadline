import { beforeEach, expect, test, vi } from "vitest";

import type { Language, SettingsOut } from "../api";
import { putLanguage } from "./api";
import {
  chooseLanguage,
  choosingLanguage,
  resetLanguageSave,
} from "./languageSave";

vi.mock("./api", () => ({ putLanguage: vi.fn() }));

const settings: SettingsOut = {
  max_heart_rate: null,
  resting_heart_rate: null,
  zone_boundary_1: null,
  zone_boundary_2: null,
  timezone: "UTC",
  review_weekday: 0,
  send_notes_to_ai: true,
  language: "en",
  ingest_token_last_four: null,
};

/** 保存の返事を、テストの側で 1 つずつ返す。返すまで保存は終わらない */
function holdLanguageSaves() {
  const pending: (() => void)[] = [];
  vi.mocked(putLanguage).mockImplementation(
    (language: Language) =>
      new Promise((resolve) => {
        pending.push(() => resolve({ ...settings, language }));
      }),
  );
  return {
    /** 送った言語とトークン。送った順 */
    sent: () => vi.mocked(putLanguage).mock.calls,
    answer: async (i: number) => {
      await vi.waitFor(() => expect(pending[i]).toBeDefined());
      pending[i]();
    },
  };
}

/** ログインした人。トークンで誰の保存かを見分ける */
function account(token: string) {
  return { getIdToken: async () => token, apply: vi.fn() };
}

/** 待っている処理を先に進める */
function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
  vi.clearAllMocks();
  resetLanguageSave();
});

test("保存中に別の人がログインしたら、前の人のリクエストが終わってからその人の最後の選択を送り、前の人の返事では画面を変えない", async () => {
  const saves = holdLanguageSaves();
  const a = account("token-a");
  const b = account("token-b");
  chooseLanguage("ja", a);
  await vi.waitFor(() => expect(saves.sent()).toEqual([["ja", "token-a"]]));

  // A がログアウトし、B がログインした
  resetLanguageSave();
  chooseLanguage("en", b);
  chooseLanguage("ja", b);
  await flush();
  // A のリクエストが終わるまで、B の分は送らない
  expect(saves.sent()).toEqual([["ja", "token-a"]]);
  await saves.answer(0);
  await saves.answer(1);

  await vi.waitFor(() => expect(b.apply).toHaveBeenCalledWith("ja"));
  // 待っている間に選び直した分は、最後の選択だけを送る
  expect(saves.sent()).toEqual([
    ["ja", "token-a"],
    ["ja", "token-b"],
  ]);
  expect(b.apply).toHaveBeenCalledTimes(1);
  expect(a.apply).not.toHaveBeenCalled();
  expect(choosingLanguage()).toBeNull();
});

test("保存中にログアウトしたら、あとから届いた返事で画面を変えない", async () => {
  const saves = holdLanguageSaves();
  const a = account("token-a");
  chooseLanguage("ja", a);
  await vi.waitFor(() => expect(saves.sent()).toHaveLength(1));

  resetLanguageSave();
  await saves.answer(0);
  await flush();

  expect(a.apply).not.toHaveBeenCalled();
  expect(choosingLanguage()).toBeNull();
});

test("トークンの取得を待つ間に同じ人が入り直したら、前の選択は送らない", async () => {
  const saves = holdLanguageSaves();
  let giveToken: () => void = () => {};
  const before = {
    getIdToken: () =>
      new Promise<string>((resolve) => {
        giveToken = () => resolve("token-a1");
      }),
    apply: vi.fn(),
  };
  const after = account("token-a2");
  chooseLanguage("ja", before);

  // 同じ人がログアウトして、入り直した
  resetLanguageSave();
  chooseLanguage("en", after);
  await saves.answer(0);
  await vi.waitFor(() => expect(after.apply).toHaveBeenCalledWith("en"));
  giveToken();
  await flush();

  expect(saves.sent()).toEqual([["en", "token-a2"]]);
  expect(before.apply).not.toHaveBeenCalled();
});

test("送ったあとに同じ人が入り直したら、前のリクエストが終わってから新しい選択を送る", async () => {
  const saves = holdLanguageSaves();
  const before = account("token-a1");
  const after = account("token-a2");
  chooseLanguage("ja", before);
  await vi.waitFor(() => expect(saves.sent()).toEqual([["ja", "token-a1"]]));

  // 同じ人がログアウトして、入り直した
  resetLanguageSave();
  chooseLanguage("en", after);
  await flush();
  // 並べて送ると、後からサーバーに届いた日本語が残ることがある
  expect(saves.sent()).toEqual([["ja", "token-a1"]]);
  await saves.answer(0);
  await vi.waitFor(() =>
    expect(saves.sent()).toEqual([
      ["ja", "token-a1"],
      ["en", "token-a2"],
    ]),
  );
  await saves.answer(1);

  await vi.waitFor(() => expect(after.apply).toHaveBeenCalledWith("en"));
  expect(before.apply).not.toHaveBeenCalled();
});
