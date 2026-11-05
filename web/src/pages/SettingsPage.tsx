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

/** 心拍の幅の上に、強度の 3 つの帯を並べた見本。4 つの値がそろって順に並んでいるときだけ出す。
 * 帯の幅は心拍の幅に比べた長さ。数字は入力欄の値をそのまま使う */
function ZonePreview({ form }: { form: SettingsIn }) {
  const {
    resting_heart_rate: resting,
    zone_boundary_1: low,
    zone_boundary_2: high,
    max_heart_rate: max,
  } = form;
  if (resting == null || low == null || high == null || max == null) {
    return null;
  }
  if (!(resting < low && low < high && high < max)) return null;
  const span = max - resting;
  const parts = [
    { name: "Low", from: resting, to: low, className: "low" },
    { name: "Mid", from: low, to: high, className: "mid" },
    { name: "High", from: high, to: max, className: "high" },
  ];
  return (
    <div className="zone-preview" aria-hidden="true">
      <div className="zone-preview-bar">
        {parts.map((p) => (
          <span
            key={p.name}
            className={p.className}
            style={{ width: `${((p.to - p.from) / span) * 100}%` }}
          >
            {p.name}
          </span>
        ))}
      </div>
      <div className="zone-preview-ticks">
        {[resting, low, high, max].map((v, i) => (
          <span key={i} style={{ left: `${((v - resting) / span) * 100}%` }}>
            {v}
          </span>
        ))}
      </div>
    </div>
  );
}

const NOT_DELETED =
  "Could not delete your account. Nothing was deleted. Please try again.";
const UNCONFIRMED =
  "Couldn't confirm whether your account was deleted. Please try again.";

/** 消したか、消せなかったときの文言。 */
type DeleteOutcome = { deleted: true } | { deleted: false; message: string };

/** 消してみて、結果を分ける。消えたと分かれば deleted。 */
async function tryDelete(user: User): Promise<DeleteOutcome> {
  let idToken: string;
  try {
    idToken = await user.getIdToken();
  } catch (e) {
    // 利用者が消えていると、Firebase はトークンの更新を user-token-expired で断る。
    // このときは SDK もログアウトする。ほかの失敗は一時的なこともあるので決めつけない
    const code = (e as { code?: unknown } | null)?.code;
    return code === "auth/user-token-expired"
      ? { deleted: true }
      : { deleted: false, message: UNCONFIRMED };
  }
  try {
    await deleteAccount(idToken);
    return { deleted: true };
  } catch (e) {
    if (e instanceof ApiError) {
      // 消したあとのやり直しは 401 になる
      if (e.status === 401) return { deleted: true };
      if (e.status === 403) {
        return { deleted: false, message: "Guests can't delete the account." };
      }
      // api は Firebase で失敗したら何も消さずに 502 を返す
      if (e.status === 502) return { deleted: false, message: NOT_DELETED };
    }
    // 通信が切れたなど。api の側で消し終わっているかもしれない
    return { deleted: false, message: UNCONFIRMED };
  }
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
  // 削除の節で切り替えたあと、描画が済んでからフォーカスを移す先
  const focusNext = useRef<"open" | "cancel" | "confirm" | null>(null);
  const openRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  // ゲストはデモの設定を見るだけ。保存、トークンの発行、削除は押せない
  const guest = user.isAnonymous;

  useEffect(() => {
    const target = focusNext.current;
    if (target === null) return;
    focusNext.current = null;
    const refs = { open: openRef, cancel: cancelRef, confirm: confirmRef };
    refs[target].current?.focus();
  });

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
    if (!form || guest) return;
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
    const outcome = await tryDelete(user);
    if (outcome.deleted) {
      // 止めたまま App に渡す。この画面はすぐ外れる
      onDeleted();
      return;
    }
    setDeleteError(outcome.message);
    deletingNow.current = false;
    setDeleting(false);
    // 消している間はボタンが止まり、フォーカスが外れることがある
    focusNext.current = "confirm";
  }

  function openDelete() {
    // 取り返しがつかないので、最初に当たるのはやめるほう
    focusNext.current = "cancel";
    setConfirmingDelete(true);
  }

  function cancelDelete() {
    focusNext.current = "open";
    setConfirmingDelete(false);
    setDeleteError(null);
  }

  const ingestUrl = `${import.meta.env.VITE_API_URL || window.location.origin}/ingest`;

  return (
    <section className="page narrow" aria-labelledby="settings-heading">
      <h2 id="settings-heading">Settings</h2>
      {guest && (
        <p className="muted">
          Guests can view the demo settings but can't change them.
        </p>
      )}
      {/* 設定を読めなくても、削除の節は出す */}
      {form ? (
        <>
          {/* 確かめるのは settingsProblem に任せる。ブラウザの吹き出しで止めると、文言が
              ブラウザごとに違い、テストでも確かめられないため。min と max は矢印の範囲の目安 */}
          <form onSubmit={handleSave} noValidate className="stack">
            <fieldset disabled={guest} className="plain stack">
              <fieldset className="card">
                <legend className="card-title">Heart rate</legend>
                <p className="muted small">
                  Your zones and daily load are calculated from these. Changing
                  them recalculates your history.
                </p>
                <div className="field-grid">
                  {HEART_RATE_FIELDS.map(({ field, label, min, max }) => (
                    <div className="field" key={field}>
                      <label htmlFor={`settings-${field}`}>{label}</label>
                      <div className="with-unit">
                        <input
                          id={`settings-${field}`}
                          type="number"
                          min={min}
                          max={max}
                          step={1}
                          value={form[field] ?? ""}
                          onChange={(e) => update(field, toInt(e.target.value))}
                        />
                        <span className="muted small">bpm</span>
                      </div>
                    </div>
                  ))}
                </div>
                <ZonePreview form={form} />
              </fieldset>

              <fieldset className="card">
                <legend className="card-title">Weekly review</legend>
                <div className="field-grid">
                  <div className="field">
                    <label htmlFor="settings-timezone">Time zone</label>
                    <select
                      id="settings-timezone"
                      value={form.timezone}
                      onChange={(e) => update("timezone", e.target.value)}
                    >
                      {timezones().map((tz) => (
                        <option key={tz} value={tz}>
                          {tz}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="settings-review-day">Review day</label>
                    <select
                      id="settings-review-day"
                      value={form.review_weekday}
                      onChange={(e) =>
                        update("review_weekday", Number(e.target.value))
                      }
                    >
                      {WEEKDAYS.map((name, i) => (
                        <option key={name} value={i}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <label className="switch-row">
                  <span>
                    Let the AI read my notes
                    <span className="muted small">
                      Turn this off and your weekly review uses your numbers
                      only, not what you wrote in notes.
                    </span>
                  </span>
                  <input
                    type="checkbox"
                    role="switch"
                    className="switch"
                    checked={form.send_notes_to_ai}
                    onChange={(e) =>
                      update("send_notes_to_ai", e.target.checked)
                    }
                  />
                </label>
              </fieldset>

              <div>
                <button type="submit" className="primary">
                  Save
                </button>
              </div>
            </fieldset>
            {status && <p role="status">{status}</p>}
          </form>

          <section className="card" aria-labelledby="connection-heading">
            <h3 id="connection-heading">iPhone connection</h3>
            <dl className="rows">
              <dt>App</dt>
              <dd>Health Auto Export</dd>
              <dt>URL</dt>
              <dd>
                <code>{ingestUrl}</code>
              </dd>
              <dt>Header</dt>
              <dd>
                <code>Authorization: Bearer &lt;token&gt;</code>
              </dd>
              <dt>Token</dt>
              <dd>
                {freshToken ? (
                  <>
                    Your new token (shown only once): <code>{freshToken}</code>
                  </>
                ) : lastFour ? (
                  `Current token ends with …${lastFour}`
                ) : (
                  "No token yet."
                )}
              </dd>
            </dl>
            <button
              type="button"
              onClick={handleIssueToken}
              disabled={issuing || guest}
            >
              {lastFour ? "Reissue token" : "Issue token"}
            </button>
          </section>
        </>
      ) : (
        !error && <p className="muted">Loading…</p>
      )}

      {error && <p role="alert">{error}</p>}

      <section className="card" aria-labelledby="account-heading">
        <h3 id="account-heading">Account</h3>
        <dl className="rows">
          <dt>Signed in with</dt>
          <dd>
            {guest
              ? "Guest (demo data)"
              : `Google${user.email ? ` · ${user.email}` : ""}`}
          </dd>
        </dl>
      </section>

      <section className="card danger" aria-labelledby="delete-heading">
        <h3 id="delete-heading">Delete account</h3>
        {confirmingDelete ? (
          <>
            <p>
              This deletes your workouts, notes, weekly reviews, ingest token,
              and your sign-in account. It can't be undone.
            </p>
            <button
              ref={confirmRef}
              type="button"
              className="danger"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Delete my account"}
            </button>{" "}
            <button
              ref={cancelRef}
              type="button"
              onClick={cancelDelete}
              disabled={deleting}
            >
              Cancel
            </button>
            {deleteError && <p role="alert">{deleteError}</p>}
          </>
        ) : (
          <>
            <p className="muted small">
              Deletes your account and all your data: workouts, notes, weekly
              reviews and your token.
            </p>
            <button
              ref={openRef}
              type="button"
              className="danger"
              onClick={openDelete}
              disabled={guest}
            >
              Delete account…
            </button>
          </>
        )}
      </section>
    </section>
  );
}
