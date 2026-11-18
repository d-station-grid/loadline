import type { User } from "firebase/auth";
import { Fragment, type SubmitEvent, useEffect, useRef, useState } from "react";

import type { SettingsOut } from "../api";
import LanguageSelect from "../components/LanguageSelect";
import { getSettings, issueIngestToken, putSettings } from "../lib/api";
import { type Messages, useI18n } from "../i18n";
import {
  formFromSettings,
  settingsBody,
  settingsProblem,
  toInt,
} from "../lib/settingsForm";
import { boundariesForMax, isSuggested } from "../lib/zones";

/** 最初の送信が届いたかを確かめる間隔。送信アプリは 3 時間おきなので、急ぐ必要はない */
export const POLL_MS = 15_000;

function errorMessage(e: unknown, m: Messages): string {
  return e instanceof Error ? e.message : m.common.somethingWentWrong;
}

type Props = {
  user: User;
  /** 「あとで」と、最初のデータが届いたあとの「ダッシュボードへ」 */
  onOpenDashboard: () => void;
};

type CopyKey = "url" | "headerKey" | "headerValue";

/**
 * 導入の案内。心拍 → トークン → Health Auto Export の自動化 → ヘルスケアの許可 →
 * 最初のデータを待つ、の順に上から並べる。最初のデータが届いたか（last_received_at）は、
 * トークンを発行したあと、数秒おきに GET /settings で確かめる。
 *
 * 送信アプリの設定とヘルスケアの許可は iPhone の中のことなので、画面からは確かめられない。
 * 手順を書くだけにして、済んだかどうかは最初のデータが届いたことで分かる。
 */
export default function OnboardingPage({ user, onOpenDashboard }: Props) {
  const { m } = useI18n();
  const t = m.onboarding;
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  // 心拍の入力欄。読んだ値で始める
  const [max, setMax] = useState("");
  const [resting, setResting] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [heartRateError, setHeartRateError] = useState<string | null>(null);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  // 発行の連打よけ。設定の画面と同じく、描画を待たずに止める
  const issuingNow = useRef(false);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [copied, setCopied] = useState<CopyKey | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getSettings(await user.getIdToken());
        if (cancelled) return;
        setSettings(s);
        setMax(s.max_heart_rate?.toString() ?? "");
        setResting(s.resting_heart_rate?.toString() ?? "");
      } catch (e) {
        if (!cancelled) setLoadError(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const lastFour = settings?.ingest_token_last_four ?? null;
  const hasToken = freshToken !== null || lastFour !== null;
  const received = settings?.last_received_at != null;

  // トークンがあって、まだ届いていないあいだだけ確かめる。画面が裏にあるときは聞かない
  useEffect(() => {
    if (!hasToken || received) return;
    let cancelled = false;
    const id = window.setInterval(async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const s = await getSettings(await user.getIdToken());
        if (!cancelled && s.last_received_at != null) {
          setSettings((prev) =>
            prev ? { ...prev, last_received_at: s.last_received_at } : s,
          );
        }
      } catch {
        // 次の回にまた聞く
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [hasToken, received, user]);

  const heartRateDone =
    settings != null &&
    settings.max_heart_rate != null &&
    settings.resting_heart_rate != null &&
    settings.zone_boundary_1 != null &&
    settings.zone_boundary_2 != null;

  async function handleSaveHeartRate(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!settings || saving) return;
    setHeartRateError(null);
    setSaved(false);
    const current = formFromSettings(settings);
    const nextMax = toInt(max);
    const saved = {
      low: current.zone_boundary_1 ?? null,
      high: current.zone_boundary_2 ?? null,
    };
    // 境目が空か、前の最大心拍から出した値のままなら、新しい最大心拍から出し直す
    const { boundaries } = boundariesForMax(
      nextMax,
      saved,
      isSuggested(current.max_heart_rate ?? null, saved),
    );
    const form = {
      ...current,
      max_heart_rate: nextMax,
      resting_heart_rate: toInt(resting),
      zone_boundary_1: boundaries.low,
      zone_boundary_2: boundaries.high,
    };
    const problem = settingsProblem(form, m.settings);
    const body = settingsBody(form);
    if (problem || !body) {
      setHeartRateError(problem ?? m.settings.fillAll);
      return;
    }
    setSaving(true);
    try {
      const next = await putSettings(body, await user.getIdToken());
      // 送っている間に最初のデータが届いていれば、それを残す
      setSettings((prev) => ({
        ...next,
        last_received_at: next.last_received_at ?? prev?.last_received_at,
      }));
      setSaved(true);
    } catch (e) {
      setHeartRateError(errorMessage(e, m));
    } finally {
      setSaving(false);
    }
  }

  async function handleIssueToken() {
    if (issuingNow.current) return;
    issuingNow.current = true;
    setIssuing(true);
    setTokenError(null);
    try {
      const issued = await issueIngestToken(await user.getIdToken());
      setFreshToken(issued.token);
      setSettings((prev) =>
        prev ? { ...prev, ingest_token_last_four: issued.last_four } : prev,
      );
    } catch (e) {
      setTokenError(errorMessage(e, m));
    } finally {
      issuingNow.current = false;
      setIssuing(false);
    }
  }

  async function copy(key: CopyKey, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
    } catch {
      // コピーできないブラウザでは、表示した文字を選んで写してもらう
    }
  }

  const ingestUrl = `${import.meta.env.VITE_API_URL || window.location.origin}/ingest`;
  const headerValue = `Bearer ${freshToken ?? "<token>"}`;

  function doneMark(done: boolean) {
    return done ? <span className="onboarding-done">✓ {t.done}</span> : null;
  }

  function copyButton(key: CopyKey, text: string) {
    return (
      <button type="button" onClick={() => void copy(key, text)}>
        {copied === key ? t.token.copied : t.token.copy}
      </button>
    );
  }

  const rows = t.app.rows;
  function settingRows(keys: string[]) {
    return (
      <dl className="rows">
        {keys.map((key) => (
          <Fragment key={key}>
            <dt>{rows[key][0]}</dt>
            <dd>{rows[key][1]}</dd>
          </Fragment>
        ))}
      </dl>
    );
  }

  return (
    <section className="page narrow" aria-labelledby="onboarding-heading">
      <div className="page-head">
        <h2 id="onboarding-heading">{t.heading}</h2>
        <button type="button" className="link" onClick={onOpenDashboard}>
          {t.skip}
        </button>
      </div>
      <p className="muted">{t.lead}</p>
      {/* 心拍を入れる前でも、案内を読みやすい言語に変えられるよう、手順の前に置く */}
      <div className="onboarding-language">
        <LanguageSelect user={user} id="onboarding-language" />
      </div>

      {loadError !== null && <p role="alert">{errorMessage(loadError, m)}</p>}
      {settings === null && loadError === null && (
        <p className="muted">{m.common.loading}</p>
      )}

      {settings && (
        <ol className="onboarding-steps" aria-label={t.stepsLabel}>
          <li className="card">
            <h3>
              {t.heartRate.title} {doneMark(heartRateDone)}
            </h3>
            <p className="muted small">{t.heartRate.body}</p>
            <form onSubmit={handleSaveHeartRate} noValidate className="stack">
              <div className="onboarding-fields">
                <label>
                  {m.settings.fields.max_heart_rate}
                  <input
                    type="number"
                    inputMode="numeric"
                    min={100}
                    max={250}
                    value={max}
                    onChange={(e) => {
                      setMax(e.target.value);
                      setSaved(false);
                    }}
                  />
                </label>
                <label>
                  {m.settings.fields.resting_heart_rate}
                  <input
                    type="number"
                    inputMode="numeric"
                    min={30}
                    max={120}
                    value={resting}
                    onChange={(e) => {
                      setResting(e.target.value);
                      setSaved(false);
                    }}
                  />
                </label>
              </div>
              <div>
                <button type="submit" className="primary" disabled={saving}>
                  {t.heartRate.save}
                </button>
              </div>
              {saved && <p role="status">{t.heartRate.saved}</p>}
              {heartRateError && <p role="alert">{heartRateError}</p>}
            </form>
          </li>

          <li className="card">
            <h3>
              {t.token.title} {doneMark(hasToken)}
            </h3>
            <p className="muted small">{t.token.body}</p>
            {lastFour && !freshToken && (
              <p className="small">{t.token.existing(lastFour)}</p>
            )}
            <dl className="rows">
              <dt>{t.token.url}</dt>
              <dd>
                <code>{ingestUrl}</code> {copyButton("url", ingestUrl)}
              </dd>
              <dt>{t.token.headerKey}</dt>
              <dd>
                <code>Authorization</code>{" "}
                {copyButton("headerKey", "Authorization")}
              </dd>
              <dt>{t.token.headerValue}</dt>
              <dd>
                <code>{headerValue}</code>{" "}
                {freshToken && copyButton("headerValue", headerValue)}
              </dd>
            </dl>
            <div>
              <button
                type="button"
                className={hasToken ? undefined : "primary"}
                onClick={handleIssueToken}
                disabled={issuing}
              >
                {lastFour || freshToken ? t.token.reissue : t.token.issue}
              </button>
            </div>
            {tokenError && <p role="alert">{tokenError}</p>}
          </li>

          <li className="card">
            <h3>{t.app.title}</h3>
            <p className="small">{t.app.install}</p>
            <p className="small">{t.app.create}</p>
            <h4>{t.app.workouts}</h4>
            {settingRows(["workoutsType", "metrics"])}
            <h4>{t.app.vo2max}</h4>
            {settingRows(["vo2Type", "vo2Select", "summarize"])}
            <h4>{t.app.both}</h4>
            {settingRows([
              "type",
              "url",
              "header",
              "format",
              "range",
              "cadence",
              "enabled",
            ])}
            <p className="small">{t.app.save}</p>
          </li>

          <li className="card">
            <h3>{t.health.title}</h3>
            <p className="small">{t.health.body}</p>
            <ul className="small">
              {t.health.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <p className="muted small">{t.health.note}</p>
          </li>

          <li className="card">
            <h3>
              {t.wait.title} {doneMark(received)}
            </h3>
            {received ? (
              <>
                <p role="status">{t.wait.received}</p>
                <div>
                  <button
                    type="button"
                    className="primary"
                    onClick={onOpenDashboard}
                  >
                    {t.wait.open}
                  </button>
                </div>
              </>
            ) : (
              <p className="muted small">
                {hasToken ? t.wait.waiting : t.wait.needToken}
              </p>
            )}
          </li>
        </ol>
      )}
    </section>
  );
}
