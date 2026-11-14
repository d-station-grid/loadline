import type { User } from "firebase/auth";
import { type SubmitEvent, useEffect, useRef, useState } from "react";

import type { Language, SettingsIn, SettingsOut } from "../api";
import {
  ApiError,
  deleteAccount,
  getSettings,
  issueIngestToken,
  putSettings,
} from "../lib/api";
import { type Messages, useI18n } from "../i18n";
import { boundariesForMax, isSuggested } from "../lib/zones";

/** 選べる言語。名前は、その言語を読む人に分かるよう、その言語で書く */
const LANGUAGES: { value: Language; label: string }[] = [
  { value: "en", label: "English" },
  { value: "ja", label: "日本語" },
];

/** 曜日の名前。0 が月曜。画面の言語のロケールで書く（2024-01-01 は月曜） */
function weekdays(locale: string): string[] {
  const format = new Intl.DateTimeFormat(locale, {
    weekday: "long",
    timeZone: "UTC",
  });
  return Array.from({ length: 7 }, (_, i) =>
    format.format(new Date(Date.UTC(2024, 0, 1 + i))),
  );
}

/**
 * 選べるタイムゾーン。今の値は一覧になくても先頭に足す。ブラウザの一覧には UTC がなく、
 * 初回ログインでブラウザの値（UTC など）が保存されると、先頭の候補が選ばれて見えるため。
 */
function timezones(current: string | undefined): string[] {
  // 新しいブラウザは一覧を持っている。古いものには最低限だけ
  const intl = Intl as unknown as {
    supportedValuesOf?: (k: string) => string[];
  };
  const list = intl.supportedValuesOf?.("timeZone") ?? ["UTC", "Asia/Tokyo"];
  return !current || list.includes(current) ? list : [current, ...list];
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

/** 心拍の項目と受け付ける範囲。範囲は api の schemas/settings.py と同じにする。名前は辞書 */
const HEART_RATE_FIELDS: {
  field: HeartRateField;
  min: number;
  max: number;
}[] = [
  { field: "max_heart_rate", min: 100, max: 250 },
  { field: "resting_heart_rate", min: 30, max: 120 },
  { field: "zone_boundary_1", min: 60, max: 250 },
  { field: "zone_boundary_2", min: 60, max: 250 },
];

/** 入力中のフォーム。心拍の 4 つは空のこともある（必須にする前の利用者、入力の途中） */
type SettingsForm = Omit<SettingsOut, "ingest_token_last_four">;

/** 送る前に確かめる、心拍の 4 つがそろっているか、各項目の範囲、項目どうしの大小。api の
 * 検査と同じ決まりで、破っていれば画面に出す文言を返す。送ると 422 としか出ないため。 */
function settingsProblem(
  form: SettingsForm,
  t: Messages["settings"],
): string | null {
  for (const { field, min, max } of HEART_RATE_FIELDS) {
    const label = t.fields[field];
    const value = form[field];
    if (value == null) return t.required(label);
    if (!Number.isInteger(value) || value < min || value > max) {
      return t.outOfRange(label, min, max);
    }
  }
  const { zone_boundary_1: low, zone_boundary_2: high } = form;
  if (low != null && high != null && !(low < high)) {
    return t.boundariesOrder;
  }
  const { resting_heart_rate: resting, max_heart_rate: max } = form;
  if (resting != null && max != null && !(resting < max)) {
    return t.restingBelowMax;
  }
  return null;
}

/** 送る本文。心拍の 4 つが空なら null（settingsProblem が先に止める） */
function settingsBody(form: SettingsForm): SettingsIn | null {
  const {
    max_heart_rate,
    resting_heart_rate,
    zone_boundary_1,
    zone_boundary_2,
  } = form;
  if (
    max_heart_rate == null ||
    resting_heart_rate == null ||
    zone_boundary_1 == null ||
    zone_boundary_2 == null
  ) {
    return null;
  }
  return {
    ...form,
    max_heart_rate,
    resting_heart_rate,
    zone_boundary_1,
    zone_boundary_2,
  };
}

function errorMessage(e: unknown, m: Messages): string {
  return e instanceof Error ? e.message : m.common.somethingWentWrong;
}

/** 心拍の幅の上に、強度の 3 つの帯を並べた見本。4 つの値がそろって順に並んでいるときだけ出す。
 * 帯の幅は心拍の幅に比べた長さ。数字は入力欄の値をそのまま使う */
function ZonePreview({ form }: { form: SettingsForm }) {
  const { m } = useI18n();
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
    { name: m.zones.low, from: resting, to: low, className: "low" },
    { name: m.zones.mid, from: low, to: high, className: "mid" },
    { name: m.zones.high, from: high, to: max, className: "high" },
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

/** 消せなかった理由。文言は描くときに今の言語で出す */
type DeleteFailure = "notDeleted" | "unconfirmed" | "guestCannotDelete";

/** 消したか、消せなかった理由。 */
type DeleteOutcome =
  { deleted: true } | { deleted: false; reason: DeleteFailure };

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
      : { deleted: false, reason: "unconfirmed" };
  }
  try {
    await deleteAccount(idToken);
    return { deleted: true };
  } catch (e) {
    if (e instanceof ApiError) {
      // 消したあとのやり直しは 401 になる
      if (e.status === 401) return { deleted: true };
      if (e.status === 403) {
        return { deleted: false, reason: "guestCannotDelete" };
      }
      // api は Firebase で失敗したら何も消さずに 502 を返す
      if (e.status === 502) return { deleted: false, reason: "notDeleted" };
    }
    // 通信が切れたなど。api の側で消し終わっているかもしれない
    return { deleted: false, reason: "unconfirmed" };
  }
}

type Props = {
  user: User;
  /** 消せたあとに呼ぶ。ここから先は api を呼ばない */
  onDeleted: () => void;
};

export default function SettingsPage({ user, onDeleted }: Props) {
  // 保存した言語で、画面全体をその場で切り替える
  const { m, locale, setLanguage } = useI18n();
  const t = m.settings;
  const [form, setForm] = useState<SettingsForm | null>(null);
  // 強度の境目が、最大心拍から出した値のままか。そのままなら最大心拍に合わせて出し直す
  const [boundariesFilled, setBoundariesFilled] = useState(false);
  // 開いた時点で境目を埋めたか。埋めた値はまだ保存していないので、保存するよう案内する
  const [unsavedFill, setUnsavedFill] = useState(false);
  const [lastFour, setLastFour] = useState<string | null>(null);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  // 発行の連打よけ。disabled は描画のあとにしか効かないので、クリック直後にここで止める。
  // 同時に 2 本走らなければ、先に無効になったトークンの応答が後から届くこともない
  const issuingNow = useRef(false);
  // 保存できたか。文言は描くときに出す（保存で言語を変えたとき、新しい言語で出すため）
  const [saved, setSaved] = useState(false);
  // 設定の読み込みの失敗。文言にするのは描くとき（今の言語で出すため）
  const [loadError, setLoadError] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // 削除の連打よけ。発行と同じく、描画を待たずにここで止める
  const deletingNow = useRef(false);
  const [deleteError, setDeleteError] = useState<DeleteFailure | null>(null);
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
          setLoadError(e);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  function applySettings(s: SettingsOut) {
    const { ingest_token_last_four, ...fields } = s;
    const max = fields.max_heart_rate ?? null;
    const saved = {
      low: fields.zone_boundary_1 ?? null,
      high: fields.zone_boundary_2 ?? null,
    };
    // 心拍の 4 つは保存に必須。最大心拍があって境目が空なら、読んだ時点で埋めておく。
    // 保存した境目が初期値と同じなら、保存の後も最大心拍に追従させる
    const filled = boundariesForMax(max, saved, isSuggested(max, saved));
    setForm({
      ...fields,
      zone_boundary_1: filled.boundaries.low,
      zone_boundary_2: filled.boundaries.high,
    });
    setBoundariesFilled(filled.filled);
    setUnsavedFill(
      filled.boundaries.low !== saved.low ||
        filled.boundaries.high !== saved.high,
    );
    setLastFour(ingest_token_last_four ?? null);
  }

  function update<K extends keyof SettingsForm>(
    key: K,
    value: SettingsForm[K],
  ) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  /** 心拍の項目を変える。最大心拍を変えたら、境目が空か出した値のままなら出し直す */
  function updateHeartRate(field: HeartRateField, value: number | null) {
    if (field !== "max_heart_rate") {
      if (field === "zone_boundary_1" || field === "zone_boundary_2") {
        setBoundariesFilled(false);
        setUnsavedFill(false);
      }
      update(field, value);
      return;
    }
    if (!form) return;
    const next = boundariesForMax(
      value,
      { low: form.zone_boundary_1 ?? null, high: form.zone_boundary_2 ?? null },
      boundariesFilled,
    );
    setForm({
      ...form,
      max_heart_rate: value,
      zone_boundary_1: next.boundaries.low,
      zone_boundary_2: next.boundaries.high,
    });
    setBoundariesFilled(next.filled);
  }

  async function handleSave(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!form || guest) return;
    setError(null);
    setSaved(false);
    const problem = settingsProblem(form, t);
    const body = settingsBody(form);
    if (problem || !body) {
      setError(problem ?? t.fillAll);
      return;
    }
    try {
      const saved = await putSettings(body, await user.getIdToken());
      applySettings(saved);
      if (saved.language) setLanguage(saved.language);
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e, m));
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
      setError(errorMessage(e, m));
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
    setDeleteError(outcome.reason);
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
      <h2 id="settings-heading">{t.heading}</h2>
      {guest && <p className="muted">{t.guestNote}</p>}
      {/* 設定を読めなくても、削除の節は出す */}
      {form ? (
        <>
          {/* 確かめるのは settingsProblem に任せる。ブラウザの吹き出しで止めると、文言が
              ブラウザごとに違い、テストでも確かめられないため。min と max は矢印の範囲の目安 */}
          <form onSubmit={handleSave} noValidate className="stack">
            <fieldset disabled={guest} className="plain stack">
              <fieldset className="card">
                <legend className="card-title">{t.heartRate}</legend>
                <p className="muted small">{t.heartRateHelp}</p>
                <p className="muted small">{t.boundariesHelp}</p>
                <div className="field-grid">
                  {HEART_RATE_FIELDS.map(({ field, min, max }) => (
                    <div className="field" key={field}>
                      <label htmlFor={`settings-${field}`}>
                        {t.fields[field]}
                      </label>
                      <div className="with-unit">
                        <input
                          id={`settings-${field}`}
                          type="number"
                          min={min}
                          max={max}
                          step={1}
                          value={form[field] ?? ""}
                          onChange={(e) =>
                            updateHeartRate(field, toInt(e.target.value))
                          }
                        />
                        <span className="muted small">{t.bpm}</span>
                      </div>
                    </div>
                  ))}
                </div>
                {unsavedFill && <p className="small">{t.boundariesFilled}</p>}
                <ZonePreview form={form} />
              </fieldset>

              <fieldset className="card">
                <legend className="card-title">{t.weeklyReview}</legend>
                <div className="field-grid">
                  <div className="field">
                    <label htmlFor="settings-timezone">{t.timezone}</label>
                    <select
                      id="settings-timezone"
                      value={form.timezone}
                      onChange={(e) => update("timezone", e.target.value)}
                    >
                      {timezones(form.timezone).map((tz) => (
                        <option key={tz} value={tz}>
                          {tz}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="settings-review-day">{t.reviewDay}</label>
                    <select
                      id="settings-review-day"
                      value={form.review_weekday}
                      onChange={(e) =>
                        update("review_weekday", Number(e.target.value))
                      }
                    >
                      {weekdays(locale).map((name, i) => (
                        <option key={name} value={i}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="settings-language">{t.language}</label>
                    <select
                      id="settings-language"
                      value={form.language ?? "en"}
                      onChange={(e) =>
                        update("language", e.target.value as Language)
                      }
                    >
                      {LANGUAGES.map(({ value, label }) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <label className="switch-row">
                  <span>
                    {t.notesToAi}
                    <span className="muted small">{t.notesToAiHelp}</span>
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
                  {t.save}
                </button>
              </div>
            </fieldset>
            {saved && <p role="status">{t.saved}</p>}
          </form>

          <section className="card" aria-labelledby="connection-heading">
            <h3 id="connection-heading">{t.connection}</h3>
            <dl className="rows">
              <dt>{t.app}</dt>
              <dd>Health Auto Export</dd>
              <dt>{t.url}</dt>
              <dd>
                <code>{ingestUrl}</code>
              </dd>
              <dt>{t.header}</dt>
              <dd>
                <code>Authorization: Bearer &lt;token&gt;</code>
              </dd>
              <dt>{t.token}</dt>
              <dd>
                {freshToken ? (
                  <>
                    {t.newToken} <code>{freshToken}</code>
                  </>
                ) : lastFour ? (
                  t.tokenEndsWith(lastFour)
                ) : (
                  t.noToken
                )}
              </dd>
            </dl>
            <button
              type="button"
              onClick={handleIssueToken}
              disabled={issuing || guest}
            >
              {lastFour ? t.reissueToken : t.issueToken}
            </button>
          </section>
        </>
      ) : (
        !error &&
        loadError === null && <p className="muted">{m.common.loading}</p>
      )}

      {error && <p role="alert">{error}</p>}
      {loadError !== null && <p role="alert">{errorMessage(loadError, m)}</p>}

      <section className="card" aria-labelledby="account-heading">
        <h3 id="account-heading">{t.account}</h3>
        <dl className="rows">
          <dt>{t.signedInWith}</dt>
          <dd>
            {guest
              ? t.guestAccount
              : `Google${user.email ? ` · ${user.email}` : ""}`}
          </dd>
        </dl>
      </section>

      <section className="card danger" aria-labelledby="delete-heading">
        <h3 id="delete-heading">{t.deleteAccount}</h3>
        {confirmingDelete ? (
          <>
            <p>{t.deleteWarning}</p>
            <button
              ref={confirmRef}
              type="button"
              className="danger"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? t.deleting : t.deleteMine}
            </button>{" "}
            <button
              ref={cancelRef}
              type="button"
              onClick={cancelDelete}
              disabled={deleting}
            >
              {t.cancel}
            </button>
            {deleteError && <p role="alert">{t[deleteError]}</p>}
          </>
        ) : (
          <>
            <p className="muted small">{t.deleteSummary}</p>
            <button
              ref={openRef}
              type="button"
              className="danger"
              onClick={openDelete}
              disabled={guest}
            >
              {t.deleteOpen}
            </button>
          </>
        )}
      </section>
    </section>
  );
}
