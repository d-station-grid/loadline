import { createContext, useContext } from "react";

import type { Language } from "../api";
import { en, ja, type Messages } from "./messages";

const MESSAGES: Record<Language, Messages> = { en, ja };

/** 日付と数値の書き方に使うロケール */
const LOCALES: Record<Language, string> = { en: "en-US", ja: "ja-JP" };

export function messagesFor(language: Language): Messages {
  return MESSAGES[language];
}

export function localeOf(language: Language): string {
  return LOCALES[language];
}

/**
 * ログイン前の画面の言語。まだ利用者の設定がないので、ブラウザの言語で決める。
 * 日本語でなければ英語（api の初回ログインと同じ決め方）。
 */
export function browserLanguage(): Language {
  try {
    return navigator.language?.toLowerCase().startsWith("ja") ? "ja" : "en";
  } catch {
    return "en";
  }
}

export type I18n = {
  language: Language;
  m: Messages;
  locale: string;
  /** 設定の画面で言語を保存したとき、画面全体をその場で切り替える */
  setLanguage: (language: Language) => void;
};

// プロバイダーの外（テストで部品だけを描くときなど）は英語
export const I18nContext = createContext<I18n>({
  language: "en",
  m: en,
  locale: LOCALES.en,
  setLanguage: () => {},
});

/** 今の言語の文言とロケール */
export function useI18n(): I18n {
  return useContext(I18nContext);
}
