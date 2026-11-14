import type { ReactNode } from "react";

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
