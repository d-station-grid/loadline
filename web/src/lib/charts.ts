import type { EChartsOption, SeriesOption } from "echarts";

import type {
  DayPoint,
  NoteOut,
  Vo2MaxPoint,
  WorkoutPoint,
  ZoneSeconds,
  ZoneWeek,
} from "../api";
import { formatDay, SPORT_LABEL } from "./format";

// API の応答を ECharts の option に組み替える。描画はしないので、ここだけを単体で検査する。
// 日付の軸は time にして、[日付, 値] の組で渡す。値のない日は線が途切れる。

const NO_HEART_RATE = "No heart rate";
// 凡例の ▲ の項目。印は series と同じ三角にする（既定の丸だと、どの印の説明か分からない）
const NO_HEART_RATE_LEGEND = { name: NO_HEART_RATE, icon: "triangle" };
/** 凡例の項目。名前だけか、印の形を決めたもの */
type LegendItem = string | { name: string; icon: string };

// チャートの色。index.css の色の変数と同じ値にする（canvas には CSS の変数が届かないため）。
// 値は Figma の S08 から
export const CHART_COLORS = {
  fitness: "#0b6e77", // 差し色の深い青緑
  fatigue: "#7a8791", // 灰
  load: "#d5dde0", // 薄い灰。線より目立たせない
  noHeartRate: "#46535b",
  vo2max: "#46535b",
  vo2maxAverage: "#b4731e", // 茶
  note: "#46535b",
  ride: "#0b6e77",
  run: "#b4731e",
  zones: ["#8abdc2", "#4e939a", "#0b6e77"], // Low、Mid、High
  axis: "#79878f",
  grid: "#e5eaec",
};

// ▲ の series の共通の形。▲ の高さは置き場所にすぎない（その日の負荷 0、その週の分かった分数）ので、
// ツールチップには出さない。出すと「No heart rate: 30」と心拍のない時間に読めるため
const NO_HEART_RATE_SERIES = {
  name: NO_HEART_RATE,
  type: "scatter",
  symbol: "triangle",
  symbolSize: 10,
  color: CHART_COLORS.noHeartRate,
  tooltip: { show: false },
} as const;

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
const TEXT_STYLE = { fontFamily: "inherit", fontSize: 11 };
// 凡例は右上に、丸い印で小さく出す
const LEGEND = {
  right: 0,
  icon: "circle",
  itemWidth: 10,
  itemHeight: 10,
  textStyle: { color: "#46535b", fontSize: 12 },
} as const;

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
  const legend: LegendItem[] = ["Fitness", "Fatigue", "Load"];
  if (missing.length > 0) legend.push(NO_HEART_RATE_LEGEND);
  return {
    textStyle: TEXT_STYLE,
    tooltip: { trigger: "axis" },
    legend: { ...LEGEND, data: legend },
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
            // ラベルは線の上の端に、線に沿って縦に出す。本文はメモの一覧で読める
            label: {
              show: true,
              position: "insideEndTop",
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
        lineStyle: { width: 1.5 },
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
        ...NO_HEART_RATE_SERIES,
        yAxisIndex: 1,
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
    legend: { ...LEGEND, data: ["VO2max", "30-day average"] },
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
  const bottomLegend = (bottom.legend as { data: LegendItem[] }).data;
  const bottomSeries = bottom.series as SeriesOption[];
  if (days.length === 0) {
    return {
      ...bottom,
      grid: { ...TREND_GRIDS[1], top: 48 },
      xAxis: { ...TIME_AXIS, ...range },
    };
  }
  const top = loadOption(days, notes);
  const topLegend = (top.legend as { data: LegendItem[] }).data;
  const lines = noteLines(days, notes);
  return {
    textStyle: TEXT_STYLE,
    tooltip: { trigger: "axis" },
    // ツールチップはマウスのある段だけに出す。上下をつなぐと、下の段は近い測定の日に
    // 吸い寄せられ、別の日付の値が混ざるため
    legend: { ...LEGEND, data: [...topLegend, ...bottomLegend], top: 0 },
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
      // 見えない棒。ECharts は棒のある時間の軸を棒の幅の半分だけ広げる。上の段の Load は
      // 凡例で消せるので、凡例に載らない見えない棒を上下の段の両方に置き、Load の表示に
      // かかわらず両段を同じだけ広げる
      ...[0, 1].map((i): SeriesOption => ({
        type: "bar",
        xAxisIndex: i,
        yAxisIndex: i === 0 ? 1 : 2,
        // 上の段では Load の棒と同じ場所に重ね、Load の棒を細くしない
        barGap: "-100%",
        silent: true,
        tooltip: { show: false },
        data: days.map((d) => [d.day, null]),
      })),
    ],
  };
}

/**
 * 時間の軸の位置（ミリ秒）を、いちばん近い日（YYYY-MM-DD）にする。ECharts は日付だけの
 * 値を端末の時刻の 0 時として置くので、端末の時刻で読む。
 */
export function dayFromTime(ms: number): string {
  const d = new Date(ms + 12 * 3600 * 1000);
  d.setHours(0, 0, 0, 0);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** ECharts のインスタンスのうち、dayAt が使う分だけ */
type PixelFinder = {
  containPixel: (finder: { gridIndex: number }, point: number[]) => boolean;
  convertFromPixel: (
    finder: { gridIndex: number },
    point: number[],
  ) => number | number[];
};

/**
 * 上下 2 段のどちらかの描画範囲の中なら、その位置の日を返す。範囲の外なら null。
 * 軸（xAxisIndex）で問い合わせると、ECharts は範囲の中かを判定できず、値も NaN になる。段（gridIndex）で聞く。
 */
export function dayAt(instance: PixelFinder, point: number[]): string | null {
  for (const gridIndex of [0, 1]) {
    if (!instance.containPixel({ gridIndex }, point)) continue;
    const value = instance.convertFromPixel({ gridIndex }, point);
    const time = Array.isArray(value) ? value[0] : NaN;
    if (Number.isFinite(time)) return dayFromTime(time);
  }
  return null;
}

export type ZoneRow = {
  key: "low" | "mid" | "high";
  label: string;
  sec: number;
  /** 3 つの合計に占める割合（%、整数）。表に出す。丸めるので合計が 100 にならないことがある */
  percent: number;
  /** 3 つの合計に占める割合（%、丸めない）。帯の幅に使う。合計は 100（時間が全部 0 なら 0） */
  width: number;
  color: string;
};

/** 強度ごとの時間を、低・中・高の順に、割合と色を添えて並べる。境目が未設定で zones が null なら null。 */
export function zoneRows(zones: ZoneSeconds | null): ZoneRow[] | null {
  if (zones === null) return null;
  const total = zones.low + zones.mid + zones.high;
  const rows = [
    { key: "low", label: "Low", sec: zones.low },
    { key: "mid", label: "Mid", sec: zones.mid },
    { key: "high", label: "High", sec: zones.high },
  ] as const;
  return rows.map((r, i) => ({
    ...r,
    percent: total === 0 ? 0 : Math.round((r.sec / total) * 100),
    width: total === 0 ? 0 : (r.sec / total) * 100,
    color: CHART_COLORS.zones[i],
  }));
}

/**
 * 週ごとの強度の時間（分）の積み上げ棒。横は週の初日。api が until から 7 日ずつ区切った順に並べる。
 * 心拍のない回は api が足していないので、その回を含む週は棒の上に ▲ を置く。
 * 0 分の棒を、休んだ週と読み違えないようにするため。
 */
export function zoneWeeksOption(weeks: ZoneWeek[]): EChartsOption {
  const labels = weeks.map((w) => formatDay(w.start));
  const missing = weeks.flatMap((w, i) =>
    w.workouts_without_zones > 0
      ? [[labels[i], toMinutes(w.zones.low + w.zones.mid + w.zones.high)]]
      : [],
  );
  const legend: LegendItem[] = ["Low", "Mid", "High"];
  if (missing.length > 0) legend.push(NO_HEART_RATE_LEGEND);
  const zones = [
    { name: "Low", key: "low" },
    { name: "Mid", key: "mid" },
    { name: "High", key: "high" },
  ] as const;
  return {
    textStyle: TEXT_STYLE,
    tooltip: { trigger: "axis" },
    // 凡例は上に取った余白に置く。位置を決めないと下に出て、棒の下の端に重なる
    legend: { ...LEGEND, data: legend, top: 0 },
    grid: { top: 36, bottom: 28, left: 40, right: 8 },
    xAxis: {
      type: "category",
      data: labels,
      axisLabel: { hideOverlap: true, color: CHART_COLORS.axis },
      axisLine: { lineStyle: { color: CHART_COLORS.grid } },
      axisTick: { show: false },
    },
    yAxis: { ...VALUE_AXIS, name: "min" },
    series: [
      ...zones.map((z, i): SeriesOption => ({
        name: z.name,
        type: "bar",
        stack: "zones",
        color: CHART_COLORS.zones[i],
        data: weeks.map((w) => toMinutes(w.zones[z.key])),
      })),
      {
        ...NO_HEART_RATE_SERIES,
        // 棒の上の端に重ならないよう、印を少し上にずらす
        symbolOffset: [0, -10],
        data: missing,
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
    legend: {
      ...LEGEND,
      data: sports.map(sportLabel),
      top: "bottom",
      right: "center",
    },
    grid: { top: 28, bottom: 56, left: 40, right: 24 },
    xAxis: { ...VALUE_AXIS, name: "Load" },
    yAxis: { ...VALUE_AXIS, name: "High (min)" },
    series: sports.map((sport) => ({
      name: sportLabel(sport),
      type: "scatter",
      symbolSize: 7,
      color: sportColor(sport),
      itemStyle: { opacity: 0.75 },
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
