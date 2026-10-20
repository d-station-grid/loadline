import type {
  Dashboard,
  IngestTokenOut,
  NoteIn,
  NoteList,
  NoteOut,
  NoteUpdate,
  ReadDashboardDashboardGetData,
  SettingsIn,
  SettingsOut,
  UserOut,
  WorkoutDetail,
  WorkoutList,
} from "../api";

const API_URL = import.meta.env.VITE_API_URL ?? "";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`API returned ${status}`);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  init: RequestInit,
  idToken: string,
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${idToken}` },
  });
  if (!res.ok) {
    throw new ApiError(res.status);
  }
  // 204 は本文がない
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

function sendJson(
  method: "POST" | "PUT" | "PATCH",
  body: unknown,
): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/** ID トークンで本人を確かめ、初回なら利用者の行を作る。 */
export function login(idToken: string): Promise<UserOut> {
  return request<UserOut>("/auth/login", { method: "POST" }, idToken);
}

export function getSettings(idToken: string): Promise<SettingsOut> {
  return request<SettingsOut>("/settings", { method: "GET" }, idToken);
}

export function putSettings(
  body: SettingsIn,
  idToken: string,
): Promise<SettingsOut> {
  return request<SettingsOut>("/settings", sendJson("PUT", body), idToken);
}

/** 取り込み用トークンを発行する。平文はこの返事でしか見られない。 */
export function issueIngestToken(idToken: string): Promise<IngestTokenOut> {
  return request<IngestTokenOut>(
    "/settings/ingest-token",
    { method: "POST" },
    idToken,
  );
}

export type WorkoutQuery = { since?: string; until?: string; limit?: number };

/** 本人のワークアウトを新しい順に。since 以上、until 未満（ISO 8601）。 */
export function getWorkouts(
  query: WorkoutQuery,
  idToken: string,
): Promise<WorkoutList> {
  const params = new URLSearchParams();
  if (query.since) params.set("since", query.since);
  if (query.until) params.set("until", query.until);
  if (query.limit) params.set("limit", String(query.limit));
  const qs = params.size > 0 ? `?${params}` : "";
  return request<WorkoutList>(`/workouts${qs}`, { method: "GET" }, idToken);
}

export function getWorkout(
  id: number,
  idToken: string,
): Promise<WorkoutDetail> {
  return request<WorkoutDetail>(`/workouts/${id}`, { method: "GET" }, idToken);
}

export type DashboardQuery = NonNullable<
  ReadDashboardDashboardGetData["query"]
>;

/**
 * 負荷と推移。since と until は利用者のタイムゾーンの日付（YYYY-MM-DD）で、両端を含む。
 * 「直近 N 週」は weeks で渡し、始まりの日は api が設定のタイムゾーンの今日から決める。
 */
export function getDashboard(
  query: DashboardQuery,
  idToken: string,
): Promise<Dashboard> {
  const params = new URLSearchParams();
  if (query.since) params.set("since", query.since);
  if (query.until) params.set("until", query.until);
  if (query.sport) params.set("sport", query.sport);
  if (query.weeks) params.set("weeks", String(query.weeks));
  const qs = params.size > 0 ? `?${params}` : "";
  return request<Dashboard>(`/dashboard${qs}`, { method: "GET" }, idToken);
}

export type NoteQuery = { since?: string; until?: string };

/** 本人のメモを新しい日付から。since 以上、until 未満（YYYY-MM-DD）。 */
export function getNotes(query: NoteQuery, idToken: string): Promise<NoteList> {
  const params = new URLSearchParams();
  if (query.since) params.set("since", query.since);
  if (query.until) params.set("until", query.until);
  const qs = params.size > 0 ? `?${params}` : "";
  return request<NoteList>(`/notes${qs}`, { method: "GET" }, idToken);
}

/** メモを 1 件書く。その日にもうあれば 409、未来の日付は 400。 */
export function addNote(body: NoteIn, idToken: string): Promise<NoteOut> {
  return request<NoteOut>("/notes", sendJson("POST", body), idToken);
}

/** メモの本文を直す。日付は変えない。本人のメモでなければ 404。 */
export function editNote(
  id: number,
  body: NoteUpdate,
  idToken: string,
): Promise<NoteOut> {
  return request<NoteOut>(`/notes/${id}`, sendJson("PATCH", body), idToken);
}

/** メモを消す。本人のメモでなければ 404。 */
export function deleteNote(id: number, idToken: string): Promise<void> {
  return request<void>(`/notes/${id}`, { method: "DELETE" }, idToken);
}
