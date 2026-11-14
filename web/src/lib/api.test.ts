import { afterEach, expect, test, vi } from "vitest";

import { login } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stubFetch() {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: 1, email: "taro@example.com" }), {
      status: 200,
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

test("login はブラウザのタイムゾーンを本文に入れて送る", async () => {
  const fetchMock = stubFetch();
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
    timeZone: "America/New_York",
  } as Intl.ResolvedDateTimeFormatOptions);

  await login("token");

  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toMatch(/\/auth\/login$/);
  expect(init.method).toBe("POST");
  expect(init.headers).toMatchObject({
    Authorization: "Bearer token",
    "Content-Type": "application/json",
  });
  expect(JSON.parse(init.body as string)).toEqual({
    timezone: "America/New_York",
  });
});

test("タイムゾーンが取れなければ、timezone を省いて送る", async () => {
  const fetchMock = stubFetch();
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(
    () => {
      throw new RangeError("no time zone");
    },
  );

  await login("token");

  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(JSON.parse(init.body as string)).toEqual({});
});
