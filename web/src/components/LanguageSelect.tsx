import type { User } from "firebase/auth";
import { useRef, useState } from "react";

import type { Language } from "../api";
import { useI18n } from "../i18n";
import { putLanguage } from "../lib/api";

/** 選べる言語。名前は、その言語を読む人に分かるよう、その言語で書く */
const LANGUAGES: { value: Language; label: string }[] = [
  { value: "en", label: "English" },
  { value: "ja", label: "日本語" },
];

type Props = {
  user: User;
  /** ラベルと選択欄をつなぐ id。設定の画面と導入の案内で別にする */
  id: string;
  disabled?: boolean;
};

/**
 * 言語の選択欄。選んだ時点で言語だけを保存し（PUT /settings/language）、画面全体を
 * その言語に切り替える。心拍の設定とは別に送るので、心拍がそろっていなくても変えられる。
 *
 * 選択欄の値は今の画面の言語。ログインした人の画面の言語は、保存済みの言語と同じ。
 */
export default function LanguageSelect({ user, id, disabled }: Props) {
  const { m, language, setLanguage } = useI18n();
  // 送っている間は、選んだ言語を出しておく
  const [pending, setPending] = useState<Language | null>(null);
  const [failed, setFailed] = useState(false);
  // 続けて選び直したとき、前に送った分の返事で上書きしないよう、最後に送った分だけを使う
  const latest = useRef(0);

  async function change(next: Language) {
    const n = ++latest.current;
    setPending(next);
    setFailed(false);
    try {
      const saved = await putLanguage(next, await user.getIdToken());
      if (n !== latest.current) return;
      setLanguage(saved.language ?? next);
    } catch {
      if (n !== latest.current) return;
      setFailed(true);
    } finally {
      if (n === latest.current) setPending(null);
    }
  }

  return (
    <div className="field">
      <label htmlFor={id}>{m.settings.language}</label>
      <select
        id={id}
        value={pending ?? language}
        disabled={disabled}
        onChange={(e) => void change(e.target.value as Language)}
      >
        {LANGUAGES.map(({ value, label }) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      {failed && <p role="alert">{m.settings.languageFailed}</p>}
    </div>
  );
}
