/**
 * 設定の心拍の項目を、送る前に確かめて本文にする。設定の画面と導入の案内で使う。
 */
import type { SettingsIn, SettingsOut } from "../api";
import type { Messages } from "../i18n";

/** 空欄は null、それ以外は整数。 */
export function toInt(value: string): number | null {
  return value === "" ? null : Number(value);
}

export type HeartRateField =
  | "max_heart_rate"
  | "resting_heart_rate"
  | "zone_boundary_1"
  | "zone_boundary_2";

/** 心拍の項目と受け付ける範囲。範囲は api の schemas/settings.py と同じにする。名前は辞書 */
export const HEART_RATE_FIELDS: {
  field: HeartRateField;
  min: number;
  max: number;
}[] = [
  { field: "max_heart_rate", min: 100, max: 250 },
  { field: "resting_heart_rate", min: 30, max: 120 },
  { field: "zone_boundary_1", min: 60, max: 250 },
  { field: "zone_boundary_2", min: 60, max: 250 },
];

/** 入力中のフォーム。心拍の 4 つは空のこともある（必須にする前の利用者、入力の途中）。
 * トークンの末尾と最後に届いた日時は読むだけの項目なので、保存の本文に混ぜない。
 * 言語は選んだ時点で PUT /settings/language に送るので、これも混ぜない（省けば api は
 * 保存済みの言語を残す） */
export type SettingsForm = Omit<
  SettingsOut,
  "ingest_token_last_four" | "last_received_at" | "language"
>;

/** 読んだ設定からフォームを作る。読むだけの項目（トークンの末尾、最後に届いた日時）と、
 * 別に保存する言語は外す */
export function formFromSettings(s: SettingsOut): SettingsForm {
  const {
    ingest_token_last_four: _lastFour,
    last_received_at: _lastReceivedAt,
    language: _language,
    ...fields
  } = s;
  return fields;
}

/** 送る前に確かめる、心拍の 4 つがそろっているか、各項目の範囲、項目どうしの大小。api の
 * 検査と同じ決まりで、破っていれば画面に出す文言を返す。送ると 422 としか出ないため。 */
export function settingsProblem(
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
export function settingsBody(form: SettingsForm): SettingsIn | null {
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
