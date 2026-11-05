// 文字の幅を測れる node で動かす。jsdom では ECharts の配置が画面と変わる
// @vitest-environment node
import * as echarts from "echarts";
import { afterEach, beforeEach, expect, test } from "vitest";

import { dayAt, trendOption } from "./charts";

let chart: echarts.ECharts;

beforeEach(() => {
  chart = echarts.init(null, null, {
    renderer: "svg",
    ssr: true,
    width: 600,
    height: 400,
  });
  const day = (d: string) => ({
    day: d,
    load: 50,
    fitness: 30,
    fatigue: 40,
    headroom: 0,
  });
  chart.setOption(
    trendOption(
      [day("2026-10-01"), day("2026-10-15"), day("2026-10-31")],
      [{ day: "2026-10-15", value: 48, average: 47.5 }],
      [],
      { since: "2026-10-01", until: "2026-10-31" },
    ),
  );
});

afterEach(() => chart.dispose());

const oct15 = new Date("2026-10-15T00:00:00").getTime();

test("上の段（体力・疲労）を押した位置から、その日を返す", () => {
  const point = chart.convertToPixel({ gridIndex: 0 }, [oct15, 30]);
  expect(dayAt(chart, point)).toBe("2026-10-15");
});

test("下の段（VO2max）を押しても、その日を返す", () => {
  const point = chart.convertToPixel({ gridIndex: 1 }, [oct15, 48]);
  expect(dayAt(chart, point)).toBe("2026-10-15");
});

test("段のあいだや軸の外を押したときは null を返す", () => {
  // 上の段は 64〜234px、下の段は 274〜374px、左右は 56px の内側
  expect(dayAt(chart, [300, 254])).toBeNull();
  expect(dayAt(chart, [20, 100])).toBeNull();
  expect(dayAt(chart, [300, 390])).toBeNull();
});
