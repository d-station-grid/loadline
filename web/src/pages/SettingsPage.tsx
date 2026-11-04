import type { User } from "firebase/auth";
import { type SubmitEvent, useEffect, useRef, useState } from "react";

import type { SettingsIn, SettingsOut } from "../api";
import {
  ApiError,
  deleteAccount,
  getSettings,
  issueIngestToken,
  putSettings,
} from "../lib/api";

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

type HeartRateField =
  | "max_heart_rate"
  | "resting_heart_rate"
  | "zone_boundary_1"
  | "zone_boundary_2";

/** 心拍の項目の名前と受け付ける範囲。範囲は api の schemas/settings.py と同じにする。 */
const HEART_RATE_FIELDS: {
  field: HeartRateField;
  label: string;
  min: number;
  max: number;
}[] = [
  { field: "max_heart_rate", label: "Max heart rate", min: 100, max: 250 },
  {
    field: "resting_heart_rate",
    label: "Resting heart rate",
    min: 30,
    max: 120,
  },
  { field: "zone_boundary_1", label: "Low / Mid boundary", min: 60, max: 250 },
  { field: "zone_boundary_2", label: "Mid / High boundary", min: 60, max: 250 },
];

/** 送る前に確かめる、各項目の範囲と、項目どうしの大小。api の検査と同じ決まりで、
 * 破っていれば画面に出す文言を返す。送ると 422 としか出ないため。 */
function settingsProblem(form: SettingsIn): string | null {
  for (const { field, label, min, max } of HEART_RATE_FIELDS) {
    const value = form[field];
    if (value == null) continue;
    if (!Number.isInteger(value) || value < min || value > max) {
      return `${label} must be a whole number from ${min} to ${max}.`;
    }
  }
  const { zone_boundary_1: low, zone_boundary_2: high } = form;
  if (low != null && high != null && !(low < high)) {
    return "Low / Mid boundary must be lower than Mid / High boundary.";
  }
  const { resting_heart_rate: resting, max_heart_rate: max } = form;
  if (resting != null && max != null && !(resting < max)) {
    return "Resting heart rate must be lower than max heart rate.";
  }
  return null;
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

/** 消すのに失敗したときの文言。api は Firebase で失敗したら何も消さずに 502 を返す。 */
function deleteErrorMessage(e: unknown): string {
  if (e instanceof ApiError && e.status === 403) {
    return "Guests can't delete the account.";
  }
  return "Could not delete your account. Nothing was deleted. Please try again.";
}

type Props = {
  user: User;
  /** 消せたあとに呼ぶ。ここから先は api を呼ばない */
  onDeleted: () => void;
};

export default function SettingsPage({ user, onDeleted }: Props) {
  const [form, setForm] = useState<SettingsIn | null>(null);
  const [lastFour, setLastFour] = useState<string | null>(null);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  // 発行の連打よけ。disabled は描画のあとにしか効かないので、クリック直後にここで止める。
  // 同時に 2 本走らなければ、先に無効になったトークンの応答が後から届くこともない
  const issuingNow = useRef(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // 削除の連打よけ。発行と同じく、描画を待たずにここで止める
  const deletingNow = useRef(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
    const problem = settingsProblem(form);
    if (problem) {
      setError(problem);
      return;
    }
    try {
      applySettings(await putSettings(form, await user.getIdToken()));
      setStatus("Saved");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function handleIssueToken() {
    if (issuingNow.current) return;
    issuingNow.current = true;
    setIssuing(true);
    setError(null);
    try {
      const t = await issueIngestToken(await user.getIdToken());
      setFreshToken(t.token);
      setLastFour(t.last_four);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      issuingNow.current = false;
      setIssuing(false);
    }
  }

  async function handleDelete() {
    if (deletingNow.current) return;
    deletingNow.current = true;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteAccount(await user.getIdToken());
    } catch (e) {
      setDeleteError(deleteErrorMessage(e));
      deletingNow.current = false;
      setDeleting(false);
      return;
    }
    // 消せたら止めたまま App に渡す。この画面はすぐ外れる
    onDeleted();
  }

  if (!form) {
    return error ? <p role="alert">{error}</p> : <p>Loading…</p>;
  }

  const ingestUrl = `${import.meta.env.VITE_API_URL || window.location.origin}/ingest`;

  return (
    <section>
      <h2>Settings</h2>
      {/* 確かめるのは settingsProblem に任せる。ブラウザの吹き出しで止めると、文言が
          ブラウザごとに違い、テストでも確かめられないため。min と max は矢印の範囲の目安 */}
      <form onSubmit={handleSave} noValidate>
        <fieldset>
          <legend>Heart rate</legend>
          {HEART_RATE_FIELDS.map(({ field, label, min, max }) => (
            <label key={field}>
              {label}
              <input
                type="number"
                min={min}
                max={max}
                step={1}
                value={form[field] ?? ""}
                onChange={(e) => update(field, toInt(e.target.value))}
              />
            </label>
          ))}
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
        <button type="button" onClick={handleIssueToken} disabled={issuing}>
          {lastFour ? "Reissue token" : "Issue token"}
        </button>
      </section>

      {error && <p role="alert">{error}</p>}

      <section>
        <h3>Delete account</h3>
        {confirmingDelete ? (
          <>
            <p>
              This deletes your workouts, notes, weekly reviews, ingest token,
              and your sign-in account. It can't be undone.
            </p>
            <button type="button" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete my account"}
            </button>{" "}
            <button
              type="button"
              onClick={() => {
                setConfirmingDelete(false);
                setDeleteError(null);
              }}
              disabled={deleting}
            >
              Cancel
            </button>
            {deleteError && <p role="alert">{deleteError}</p>}
          </>
        ) : (
          <button type="button" onClick={() => setConfirmingDelete(true)}>
            Delete account…
          </button>
        )}
      </section>
    </section>
  );
}
