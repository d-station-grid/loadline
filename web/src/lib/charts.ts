import type { EChartsOption } from "echarts";

import type { DayPoint, Vo2MaxPoint, WorkoutPoint, ZoneSeconds } from "../api";
import { SPORT_LABEL } from "./format";

// API の応答を ECharts の option に組み替える。描画はしないので、ここだけを単体で検査する。
// 日付の軸は time にして、[日付, 値] の組で渡す。値のない日は線が途切れる。

/** 体力・疲労の線と、日々の負荷の棒。負荷が null の日は棒を出さない。 */
export function loadOption(days: DayPoint[]): EChartsOption {
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["Fitness", "Fatigue", "Load"] },
    xAxis: { type: "time" },
    yAxis: [
      { type: "value", name: "Fitness / Fatigue" },
      { type: "value", name: "Load", splitLine: { show: false } },
    ],
    series: [
      {
        name: "Fitness",
        type: "line",
        showSymbol: false,
        data: days.map((d) => [d.day, round1(d.fitness)]),
      },
      {
        name: "Fatigue",
        type: "line",
        showSymbol: false,
        data: days.map((d) => [d.day, round1(d.fatigue)]),
      },
      {
        name: "Load",
        type: "bar",
        yAxisIndex: 1,
        data: days.map((d) => [d.day, d.load === null ? null : round1(d.load)]),
      },
    ],
  };
}

/** 測定ごとの点と、30 日平均の線。 */
export function vo2maxOption(points: Vo2MaxPoint[]): EChartsOption {
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["VO2max", "30-day average"] },
    xAxis: { type: "time" },
    yAxis: { type: "value", name: "ml/kg/min", scale: true },
    series: [
      {
        name: "VO2max",
        type: "scatter",
        data: points.map((p) => [p.day, round1(p.value)]),
      },
      {
        name: "30-day average",
        type: "line",
        showSymbol: false,
        data: points.map((p) => [p.day, round1(p.average)]),
      },
    ],
  };
}

/** 強度ごとの時間を分で。境目が未設定で zones が null なら、チャートは出さない。 */
export function zonesOption(zones: ZoneSeconds | null): EChartsOption | null {
  if (zones === null) return null;
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: ["Low", "Mid", "High"] },
    yAxis: { type: "value", name: "min" },
    series: [
      {
        name: "Time",
        type: "bar",
        data: [zones.low, zones.mid, zones.high].map(toMinutes),
      },
    ],
  };
}

/** 1 回ごとの負荷（横）と高強度の時間（縦、分）。種目ごとに色を分け、どちらかが null の回は除く。 */
export function workoutsOption(workouts: WorkoutPoint[]): EChartsOption {
  const sports = [...new Set(workouts.map((w) => w.sport))];
  return {
    tooltip: { trigger: "item" },
    legend: { data: sports.map(sportLabel) },
    xAxis: { type: "value", name: "Load" },
    yAxis: { type: "value", name: "High (min)" },
    series: sports.map((sport) => ({
      name: sportLabel(sport),
      type: "scatter",
      data: workouts
        .filter(
          (w) => w.sport === sport && w.load !== null && w.high_sec !== null,
        )
        .map((w) => [
          round1(w.load as number),
          toMinutes(w.high_sec as number),
        ]),
    })),
  };
}

function sportLabel(sport: string): string {
  return SPORT_LABEL[sport] ?? sport;
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

function toMinutes(sec: number): number {
  return Math.round(sec / 60);
}
