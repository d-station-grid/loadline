import { render } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { I18nProvider } from "../i18n";
import Chart from "./Chart";

// 作るときに渡したロケールを見る。描くところは本物の ECharts に任せない
const created: { locale?: string }[] = [];
vi.mock("echarts/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("echarts/core")>();
  return {
    ...actual,
    init: (_el: HTMLElement, _theme: unknown, opts: { locale?: string }) => {
      created.push(opts);
      return {
        setOption: vi.fn(),
        resize: vi.fn(),
        dispose: vi.fn(),
        getZr: () => ({ on: vi.fn() }),
      };
    },
  };
});

beforeEach(() => {
  created.length = 0;
});

test("時間軸の目盛りが画面の言語で出るよう、ECharts に言語のロケールを渡す", () => {
  render(
    <I18nProvider language="ja" setLanguage={() => {}}>
      <Chart option={{}} />
    </I18nProvider>,
  );

  expect(created).toEqual([{ locale: "JA" }]);
});

test("画面の言語が変わったら、そのロケールで作り直す", () => {
  const { rerender } = render(
    <I18nProvider language="en" setLanguage={() => {}}>
      <Chart option={{}} />
    </I18nProvider>,
  );
  rerender(
    <I18nProvider language="ja" setLanguage={() => {}}>
      <Chart option={{}} />
    </I18nProvider>,
  );

  expect(created).toEqual([{ locale: "EN" }, { locale: "JA" }]);
});
