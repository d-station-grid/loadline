import { type ReactNode, useEffect } from "react";

import type { Language } from "../api";
import { I18nContext, localeOf, messagesFor } from "./context";

export function I18nProvider({
  language,
  setLanguage,
  children,
}: {
  language: Language;
  setLanguage: (language: Language) => void;
  children: ReactNode;
}) {
  // 読み上げなどが正しい言語で読むよう、<html lang> も画面の言語に合わせる
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);
  return (
    <I18nContext.Provider
      value={{
        language,
        m: messagesFor(language),
        locale: localeOf(language),
        setLanguage,
      }}
    >
      {children}
    </I18nContext.Provider>
  );
}
