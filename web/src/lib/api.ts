import type { IngestTokenOut, SettingsIn, SettingsOut, UserOut } from "../api";

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
  return (await res.json()) as T;
}

function putJson(body: unknown): RequestInit {
  return {
    method: "PUT",
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
  return request<SettingsOut>("/settings", putJson(body), idToken);
}

/** 取り込み用トークンを発行する。平文はこの返事でしか見られない。 */
export function issueIngestToken(idToken: string): Promise<IngestTokenOut> {
  return request<IngestTokenOut>(
    "/settings/ingest-token",
    { method: "POST" },
    idToken,
  );
}
