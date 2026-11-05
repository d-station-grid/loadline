import * as echarts from "echarts";
import { afterEach, expect, test } from "vitest";

import type { DayPoint, Vo2MaxPoint } from "../api";
import { TREND_CHART_HEIGHT, trendOption } from "./charts";

// ECharts で実際に描いて、画面上の位置で確かめる。option の形だけでは、上下の段の
// 日付が同じ横の位置に来るかは分からない

const charts: echarts.ECharts[] = [];
afterEach(() => {
  charts.splice(0).forEach((c) => c.dispose());
});

function dayOf(i: number): string {
  return new Date(Date.UTC(2026, 6, 28 + i)).toISOString().slice(0, 10);
}

const days: DayPoint[] = Array.from({ length: 84 }, (_, i) => ({
  day: dayOf(i),
  load: 30,
  fitness: 40,
  fatigue: 35,
  headroom: 5,
}));

// VO2max は期間の途中からしか測っていない。それでも横の位置は上の段とそろう
const vo2max: Vo2MaxPoint[] = [20, 50, 70].map((i) => ({
  day: dayOf(i),
  value: 48,
  average: 47,
}));

test.each([960, 360])(
  "幅 %ipx でも、上の段と下の段の同じ日付が同じ横の位置に来る",
  (width) => {
    const option = trendOption(days, vo2max, [], {
      since: dayOf(0),
      until: dayOf(83),
    });
    const chart = echarts.init(null, null, {
      renderer: "svg",
      ssr: true,
      width,
      height: TREND_CHART_HEIGHT,
    });
    charts.push(chart);
    chart.setOption({ ...option, animation: false });

    for (const i of [0, 20, 50, 83]) {
      // 軸を 1 本だけ指して値を 1 つ渡すと、その軸の上の px が数で返る
      const topX = chart.convertToPixel({ xAxisIndex: 0 }, dayOf(i));
      const bottomX = chart.convertToPixel({ xAxisIndex: 1 }, dayOf(i));
      expect(bottomX).toBeCloseTo(topX as number, 5);
    }
  },
);
