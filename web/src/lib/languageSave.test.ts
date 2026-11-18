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

beforeEach(() => {
  vi.clearAllMocks();
  resetLanguageSave();
});

test("保存中にログインし直した人の選択は、前の人の保存を待たずに送り、前の人の返事では画面を変えない", async () => {
  const saves = holdLanguageSaves();
  const a = account("token-a");
  const b = account("token-b");
  chooseLanguage("ja", a);
  await vi.waitFor(() => expect(saves.sent()).toEqual([["ja", "token-a"]]));

  // A がログアウトし、B がログインした
  resetLanguageSave();
  chooseLanguage("en", b);
  chooseLanguage("ja", b);
  await saves.answer(0);
  await saves.answer(1);
  await saves.answer(2);

  await vi.waitFor(() => expect(b.apply).toHaveBeenCalledWith("ja"));
  expect(saves.sent()).toEqual([
    ["ja", "token-a"],
    ["en", "token-b"],
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
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(a.apply).not.toHaveBeenCalled();
  expect(choosingLanguage()).toBeNull();
});
