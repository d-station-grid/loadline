import { afterEach, expect, test, vi } from "vitest";

import { getCurrentReview, login } from "./api";

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

test("login はブラウザのタイムゾーンと言語を本文に入れて送る", async () => {
  const fetchMock = stubFetch();
  vi.spyOn(navigator, "language", "get").mockReturnValue("ja-JP");
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
  // 言語はそのまま送り、どの言語にするかは api が決める
  expect(JSON.parse(init.body as string)).toEqual({
    timezone: "America/New_York",
    language: "ja-JP",
  });
});

test("タイムゾーンと言語が取れなければ、省いて送る", async () => {
  const fetchMock = stubFetch();
  vi.spyOn(navigator, "language", "get").mockReturnValue("");
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(
    () => {
      throw new RangeError("no time zone");
    },
  );

  await login("token");

  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(JSON.parse(init.body as string)).toEqual({});
});

test.each([
  ["ja-JP", "ja"],
  ["en-US", "en"],
  // 先頭が日本語でなければ、画面と同じく英語
  ["fr-FR", "en"],
])(
  "どのリクエストにも、ゲストの画面の言語を付ける（ブラウザが %s なら %s）",
  async (browser, guest) => {
    // 応答の本文は 1 回しか読めないので、呼ばれるたびに作る
    const fetchMock = vi
      .fn()
      .mockImplementation(
        async () => new Response(JSON.stringify(null), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(navigator, "language", "get").mockReturnValue(browser);

    await login("token");
    await getCurrentReview("token");

    for (const [, init] of fetchMock.mock.calls as [string, RequestInit][]) {
      expect(init.headers).toMatchObject({ "X-Guest-Language": guest });
    }
    expect(fetchMock).toHaveBeenCalledTimes(2);
  },
);
