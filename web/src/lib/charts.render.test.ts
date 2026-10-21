import * as echarts from "echarts";
import { afterEach, expect, test } from "vitest";

import type { DayPoint, NoteOut } from "../api";
import { LOAD_CHART_HEIGHT, loadOption, NOTE_PIN_SIZE } from "./charts";

// ECharts で実際に描いて、画面上の位置で確かめる。option の形だけでは、吹き出しの頭が
// グリッドに収まるかは分からない（吹き出しは px で大きさが決まり、軸は値で決まるため）

const charts: echarts.ECharts[] = [];
afterEach(() => {
  charts.splice(0).forEach((c) => c.dispose());
});

function days(peak: number): DayPoint[] {
  return Array.from({ length: 84 }, (_, i) => {
    const day = new Date(Date.UTC(2026, 6, 28 + i)).toISOString().slice(0, 10);
    const fitness = i === 60 ? peak : peak * 0.5;
    return { day, load: 30, fitness, fatigue: fitness * 0.8, headroom: 0 };
  });
}

function memo(date: string, label: string): NoteOut {
  return { id: 1, date, label, body: "", created_at: "", updated_at: "" };
}

test.each([
  [960, 100],
  [960, 7],
  [360, 100],
  [360, 1234],
])(
  "幅 %ipx、体力の山が %i の日の吹き出しも、頭がグリッドの中に収まる",
  (width, peak) => {
    const data = days(peak);
    const notes = [memo(data[60].day, "Peak"), memo(data[10].day, "Low")];
    const option = loadOption(data, notes);
    const chart = echarts.init(null, null, {
      renderer: "svg",
      ssr: true,
      width,
      height: LOAD_CHART_HEIGHT,
    });
    charts.push(chart);
    chart.setOption({ ...option, animation: false });

    // グリッドの矩形は公開の API にないので、内部の model から読む
    const grid = (
      chart as unknown as {
        getModel: () => {
          getComponent: (name: string) => {
            coordinateSystem: { getRect: () => { y: number } };
          };
        };
      }
    )
      .getModel()
      .getComponent("grid")
      .coordinateSystem.getRect();
    const [fitness] = option.series as {
      markPoint: { data: { coord: [string, number] }[] };
    }[];
    for (const { coord } of fitness.markPoint.data) {
      const [, tipY] = chart.convertToPixel({ seriesIndex: 0 }, coord);
      // 吹き出しは先が coord にあり、そこから上に NOTE_PIN_SIZE の高さで描かれる
      expect(tipY - NOTE_PIN_SIZE).toBeGreaterThanOrEqual(grid.y);
    }
  },
);
