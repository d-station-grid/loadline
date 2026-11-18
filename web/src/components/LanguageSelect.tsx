import type { User } from "firebase/auth";
import { useEffect, useState, useSyncExternalStore } from "react";

import type { Language } from "../api";
import { useI18n } from "../i18n";
import {
  chooseLanguage,
  choosingLanguage,
  subscribeChoosing,
  subscribeFailure,
} from "../lib/languageSave";

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
 * 送る順番は lib/languageSave がアプリ全体でまとめる。
 *
 * 選択欄の値は、保存中なら最後に選んだ言語、そうでなければ今の画面の言語。ログインした人の
 * 画面の言語は、保存済みの言語と同じ。
 */
export default function LanguageSelect({ user, id, disabled }: Props) {
  const { m, language, setLanguage } = useI18n();
  const choosing = useSyncExternalStore(subscribeChoosing, choosingLanguage);
  const [failed, setFailed] = useState(false);
  // 閉じた画面には書き込まない。購読は開いているあいだだけ
  useEffect(() => subscribeFailure(() => setFailed(true)), []);

  function change(next: Language) {
    setFailed(false);
    chooseLanguage(next, {
      getIdToken: () => user.getIdToken(),
      apply: setLanguage,
    });
  }

  return (
    <div className="field">
      <label htmlFor={id}>{m.settings.language}</label>
      <select
        id={id}
        value={choosing ?? language}
        disabled={disabled}
        onChange={(e) => change(e.target.value as Language)}
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
