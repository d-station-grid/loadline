import type { User } from "firebase/auth";
import { type SubmitEvent, useEffect, useState } from "react";

import type { SettingsIn, SettingsOut } from "../api";
import { getSettings, issueIngestToken, putSettings } from "../lib/api";

const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

function timezones(): string[] {
  // 新しいブラウザは一覧を持っている。古いものには最低限だけ
  const intl = Intl as unknown as {
    supportedValuesOf?: (k: string) => string[];
  };
  return intl.supportedValuesOf?.("timeZone") ?? ["UTC", "Asia/Tokyo"];
}

/** 空欄は null、それ以外は整数。 */
function toInt(value: string): number | null {
  return value === "" ? null : Number(value);
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

type Props = { user: User };

export default function SettingsPage({ user }: Props) {
  const [form, setForm] = useState<SettingsIn | null>(null);
  const [lastFour, setLastFour] = useState<string | null>(null);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getSettings(await user.getIdToken());
        if (!cancelled) {
          applySettings(s);
        }
      } catch (e) {
        if (!cancelled) {
          setError(errorMessage(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  function applySettings(s: SettingsOut) {
    const { ingest_token_last_four, ...fields } = s;
    setForm(fields);
    setLastFour(ingest_token_last_four ?? null);
  }

  function update<K extends keyof SettingsIn>(key: K, value: SettingsIn[K]) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  async function handleSave(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!form) return;
    setError(null);
    setStatus(null);
    try {
      applySettings(await putSettings(form, await user.getIdToken()));
      setStatus("Saved");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function handleIssueToken() {
    setError(null);
    try {
      const t = await issueIngestToken(await user.getIdToken());
      setFreshToken(t.token);
      setLastFour(t.last_four);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (!form) {
    return error ? <p role="alert">{error}</p> : <p>Loading…</p>;
  }

  const ingestUrl = `${import.meta.env.VITE_API_URL || window.location.origin}/ingest`;

  return (
    <section>
      <h2>Settings</h2>
      <form onSubmit={handleSave}>
        <fieldset>
          <legend>Heart rate</legend>
          <label>
            Max heart rate
            <input
              type="number"
              value={form.max_heart_rate ?? ""}
              onChange={(e) => update("max_heart_rate", toInt(e.target.value))}
            />
          </label>
          <label>
            Resting heart rate
            <input
              type="number"
              value={form.resting_heart_rate ?? ""}
              onChange={(e) =>
                update("resting_heart_rate", toInt(e.target.value))
              }
            />
          </label>
          <label>
            Low / Mid boundary
            <input
              type="number"
              value={form.zone_boundary_1 ?? ""}
              onChange={(e) => update("zone_boundary_1", toInt(e.target.value))}
            />
          </label>
          <label>
            Mid / High boundary
            <input
              type="number"
              value={form.zone_boundary_2 ?? ""}
              onChange={(e) => update("zone_boundary_2", toInt(e.target.value))}
            />
          </label>
        </fieldset>

        <fieldset>
          <legend>Weekly review</legend>
          <label>
            Time zone
            <select
              value={form.timezone}
              onChange={(e) => update("timezone", e.target.value)}
            >
              {timezones().map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </label>
          <label>
            Review day
            <select
              value={form.review_weekday}
              onChange={(e) => update("review_weekday", Number(e.target.value))}
            >
              {WEEKDAYS.map((name, i) => (
                <option key={name} value={i}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={form.send_notes_to_ai}
              onChange={(e) => update("send_notes_to_ai", e.target.checked)}
            />
            Let the AI read my notes
          </label>
        </fieldset>

        <button type="submit">Save</button>
        {status && <p role="status">{status}</p>}
      </form>

      <section>
        <h3>Health Auto Export</h3>
        <p>
          Send workouts and metrics to <code>{ingestUrl}</code> with the header{" "}
          <code>Authorization: Bearer &lt;token&gt;</code>.
        </p>
        {freshToken ? (
          <p>
            Your new token (shown only once): <code>{freshToken}</code>
          </p>
        ) : (
          <p>
            {lastFour
              ? `Current token ends with …${lastFour}`
              : "No token yet."}
          </p>
        )}
        <button type="button" onClick={handleIssueToken}>
          {lastFour ? "Reissue token" : "Issue token"}
        </button>
      </section>

      {error && <p role="alert">{error}</p>}
    </section>
  );
}
