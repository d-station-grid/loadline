import type { EChartsOption, SeriesOption } from "echarts";

import type {
  DayPoint,
  NoteOut,
  Vo2MaxPoint,
  WorkoutPoint,
  ZoneSeconds,
} from "../api";
import { SPORT_LABEL } from "./format";

// API の応答を ECharts の option に組み替える。描画はしないので、ここだけを単体で検査する。
// 日付の軸は time にして、[日付, 値] の組で渡す。値のない日は線が途切れる。

const NO_HEART_RATE = "No heart rate";

// チャートの色。index.css の色の変数と同じ値にする（canvas には CSS の変数が届かないため）
export const CHART_COLORS = {
  fitness: "#0f766e", // 差し色の深い青緑
  fatigue: "#9ca3af", // 灰
  load: "#99d3cc", // 差し色を薄くしたもの。線より目立たせない
  noHeartRate: "#4b5563",
  vo2max: "#0f766e",
  vo2maxAverage: "#92400e", // 茶
  note: "#6b7280",
  ride: "#0f766e",
  run: "#b45309",
  zones: ["#99d3cc", "#2a9d8f", "#0f766e"],
  axis: "#6b7280",
  grid: "#eef0f2",
};

/** 体力・疲労と VO2max のチャートの高さ（px）。上の段と下の段を合わせた高さ */
export const TREND_CHART_HEIGHT = 420;
// 上の段（体力・疲労・負荷）と下の段（VO2max）。横の日付をそろえるため左右の余白も同じにする
const TREND_GRIDS = [
  { top: 64, height: 170, left: 56, right: 56 },
  { top: 274, height: 100, left: 56, right: 56 },
];
/** 時間の軸。ECharts は月の頭に「Oct」を置き、近くの日付の目盛りと重なることがあるので、
 * 重なった文字は間引く。 */
const TIME_AXIS = {
  type: "time",
  axisLabel: { hideOverlap: true, color: CHART_COLORS.axis },
  axisLine: { lineStyle: { color: CHART_COLORS.grid } },
} as const;
const VALUE_AXIS = {
  type: "value",
  axisLabel: { color: CHART_COLORS.axis },
  nameTextStyle: { color: CHART_COLORS.axis },
  splitLine: { lineStyle: { color: CHART_COLORS.grid } },
} as const;
// 共通の文字。ページの文字と合わせる
const TEXT_STYLE = { fontFamily: "inherit" };

/** ラベルのあるメモの縦の点線。チャートの期間の外の日と、ラベルのないメモは出さない */
function noteLines(days: DayPoint[], notes: NoteOut[]) {
  const inChart = new Set(days.map((d) => d.day));
  return notes.flatMap((n) =>
    n.label && inChart.has(n.date) ? [{ name: n.label, xAxis: n.date }] : [],
  );
}

/**
 * 体力・疲労の線と、日々の負荷の棒。負荷が null の日（心拍のないワークアウトを含む日）は
 * 棒を出さず、負荷 0 の高さに ▲ を置く。api はその日を負荷 0 として計算を続けるので、
 * 体力と疲労は低めに出る。棒を消すだけだと休養日と見分けがつかない。
 * ラベルのあるメモの日には、縦の点線とラベルを出す。
 */
export function loadOption(
  days: DayPoint[],
  notes: NoteOut[] = [],
): EChartsOption {
  const missing = days.filter((d) => d.load === null);
  const lines = noteLines(days, notes);
  // 印のない期間は凡例にも出さない。点のない series の凡例は薄く出て、壊れて見えるため
  const legend = ["Fitness", "Fatigue", "Load"];
  if (missing.length > 0) legend.push(NO_HEART_RATE);
  return {
    textStyle: TEXT_STYLE,
    tooltip: { trigger: "axis" },
    legend: { data: legend },
    grid: TREND_GRIDS[0],
    xAxis: TIME_AXIS,
    yAxis: [
      { ...VALUE_AXIS, name: "Fitness / Fatigue" },
      { ...VALUE_AXIS, name: "Load", splitLine: { show: false } },
    ],
    series: [
      {
        name: "Fitness",
        type: "line",
        showSymbol: false,
        color: CHART_COLORS.fitness,
        lineStyle: { width: 2 },
        data: days.map((d) => [d.day, round1(d.fitness)]),
        ...(lines.length > 0 && {
          markLine: {
            symbol: "none",
            silent: true,
            lineStyle: { type: "dashed", color: CHART_COLORS.note, width: 1 },
            // ラベルは線の上の端に出す。本文はメモの一覧で読める
            label: {
              show: true,
              position: "end",
              formatter: "{b}",
              color: CHART_COLORS.note,
              fontSize: 11,
            },
            data: lines,
          },
        }),
      },
      {
        name: "Fatigue",
        type: "line",
        showSymbol: false,
        color: CHART_COLORS.fatigue,
        lineStyle: { width: 2 },
        data: days.map((d) => [d.day, round1(d.fatigue)]),
      },
      {
        name: "Load",
        type: "bar",
        yAxisIndex: 1,
        color: CHART_COLORS.load,
        data: days.map((d) => [d.day, d.load === null ? null : round1(d.load)]),
      },
      {
        name: NO_HEART_RATE,
        type: "scatter",
        yAxisIndex: 1,
        symbol: "triangle",
        symbolSize: 10,
        color: CHART_COLORS.noHeartRate,
        data: missing.map((d) => [d.day, 0]),
      },
    ],
  };
}

/** 測定ごとの点と、30 日平均の線。 */
export function vo2maxOption(points: Vo2MaxPoint[]): EChartsOption {
  return {
    textStyle: TEXT_STYLE,
    tooltip: { trigger: "axis" },
    legend: { data: ["VO2max", "30-day average"] },
    grid: TREND_GRIDS[1],
    xAxis: TIME_AXIS,
    yAxis: { ...VALUE_AXIS, name: "VO2max", scale: true },
    series: [
      {
        name: "VO2max",
        type: "scatter",
        symbolSize: 6,
        color: CHART_COLORS.vo2max,
        data: points.map((p) => [p.day, round1(p.value)]),
      },
      {
        name: "30-day average",
        type: "line",
        showSymbol: false,
        color: CHART_COLORS.vo2maxAverage,
        lineStyle: { width: 2 },
        data: points.map((p) => [p.day, round1(p.average)]),
      },
    ],
  };
}

type Period = { since: string; until: string };

/**
 * 上の段に体力・疲労・負荷、下の段に VO2max を置いた 1 枚のチャート。
 * 横の軸は両方とも api が返した期間（since から until）にして、日付の位置をそろえる。
 * 心拍の設定がなく days が空のときは、上の段を出さず VO2max だけにする。
 */
export function trendOption(
  days: DayPoint[],
  vo2max: Vo2MaxPoint[],
  notes: NoteOut[],
  period: Period,
): EChartsOption {
  const range = { min: period.since, max: period.until };
  const bottom = vo2maxOption(vo2max);
  const bottomLegend = (bottom.legend as { data: string[] }).data;
  const bottomSeries = bottom.series as SeriesOption[];
  if (days.length === 0) {
    return {
      ...bottom,
      grid: { ...TREND_GRIDS[1], top: 48 },
      xAxis: { ...TIME_AXIS, ...range },
    };
  }
  const top = loadOption(days, notes);
  const topLegend = (top.legend as { data: string[] }).data;
  const lines = noteLines(days, notes);
  return {
    textStyle: TEXT_STYLE,
    tooltip: { trigger: "axis" },
    // ツールチップはマウスのある段だけに出す。上下をつなぐと、下の段は近い測定の日に
    // 吸い寄せられ、別の日付の値が混ざるため
    legend: { data: [...topLegend, ...bottomLegend], top: 0 },
    grid: TREND_GRIDS,
    xAxis: [
      // 上の段の日付は下の段と同じなので、文字は下の段だけに出す
      { ...TIME_AXIS, ...range, gridIndex: 0, axisLabel: { show: false } },
      { ...TIME_AXIS, ...range, gridIndex: 1 },
    ],
    yAxis: [
      ...(top.yAxis as object[]).map((a) => ({ ...a, gridIndex: 0 })),
      { ...(bottom.yAxis as object), gridIndex: 1 },
    ],
    series: [
      ...(top.series as SeriesOption[]),
      ...(bottomSeries.map((s, i) => ({
        ...s,
        xAxisIndex: 1,
        yAxisIndex: 2,
        // メモの点線は下の段にも引く。ラベルは上の段だけに出す
        ...(i === 0 &&
          lines.length > 0 && {
            markLine: {
              symbol: "none",
              silent: true,
              lineStyle: { type: "dashed", color: CHART_COLORS.note, width: 1 },
              label: { show: false },
              data: lines,
            },
          }),
      })) as SeriesOption[]),
      // 見えない棒。ECharts は棒のある時間の軸を棒の幅の半分だけ広げるので、
      // 下の段にも同じ日付の棒を置いて、上の段と同じだけ広げる
      {
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 2,
        silent: true,
        tooltip: { show: false },
        data: days.map((d) => [d.day, null]),
      },
    ],
  };
}

/** 強度ごとの時間を分で、横向きの棒にする。境目が未設定で zones が null なら、チャートは出さない。 */
export function zonesOption(zones: ZoneSeconds | null): EChartsOption | null {
  if (zones === null) return null;
  return {
    textStyle: TEXT_STYLE,
    tooltip: { trigger: "axis" },
    grid: { top: 16, bottom: 32, left: 48, right: 24 },
    // 低い強度から上に並べる。色は強度が上がるほど濃くする
    yAxis: {
      type: "category",
      data: ["Low", "Mid", "High"],
      inverse: true,
      axisLabel: { color: CHART_COLORS.axis },
      axisLine: { lineStyle: { color: CHART_COLORS.grid } },
      axisTick: { show: false },
    },
    xAxis: { ...VALUE_AXIS, name: "min", nameLocation: "end" },
    color: CHART_COLORS.zones,
    series: [
      {
        name: "Time",
        type: "bar",
        colorBy: "data",
        barWidth: "55%",
        data: [zones.low, zones.mid, zones.high].map(toMinutes),
      },
    ],
  };
}

/** 1 回ごとの負荷（横）と高強度の時間（縦、分）。種目ごとに色を分け、どちらかが null の回は除く。 */
export function workoutsOption(workouts: WorkoutPoint[]): EChartsOption {
  const sports = [...new Set(workouts.map((w) => w.sport))];
  return {
    textStyle: TEXT_STYLE,
    tooltip: { trigger: "item" },
    legend: { data: sports.map(sportLabel), top: 0 },
    grid: { top: 40, bottom: 40, left: 48, right: 48 },
    xAxis: { ...VALUE_AXIS, name: "Load" },
    yAxis: { ...VALUE_AXIS, name: "High (min)" },
    series: sports.map((sport) => ({
      name: sportLabel(sport),
      type: "scatter",
      symbolSize: 8,
      color: sportColor(sport),
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

function sportColor(sport: string): string | undefined {
  if (sport === "ride") return CHART_COLORS.ride;
  if (sport === "run") return CHART_COLORS.run;
  return undefined;
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
