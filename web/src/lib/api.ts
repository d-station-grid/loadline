import type { UserOut } from "../api";

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

/** ID トークンで本人を確かめ、初回なら利用者の行を作る。 */
export function login(idToken: string): Promise<UserOut> {
  return request<UserOut>("/auth/login", { method: "POST" }, idToken);
}
