import type { EChartsOption, SeriesOption } from "echarts";
import { expect, test } from "vitest";

import type { DayPoint, NoteOut, Vo2MaxPoint, WorkoutPoint } from "../api";
import {
  axisMaxForPins,
  loadOption,
  vo2maxOption,
  workoutsOption,
  zonesOption,
} from "./charts";

function seriesOf(option: EChartsOption | null): SeriesOption[] {
  return (option?.series ?? []) as SeriesOption[];
}

function point(
  over: Partial<WorkoutPoint> & Pick<WorkoutPoint, "id">,
): WorkoutPoint {
  return {
    sport: "ride",
    started_at: "2026-10-01T06:00:00+09:00",
    day: "2026-10-01",
    load: 50,
    high_sec: 600,
    ...over,
  };
}

test("体力・疲労・負荷を日付との組にし、小数 1 桁に丸める", () => {
  const days: DayPoint[] = [
    {
      day: "2026-10-01",
      load: 42.36,
      fitness: 30.04,
      fatigue: 55.56,
      headroom: -25.5,
    },
    {
      day: "2026-10-02",
      load: 0,
      fitness: 29.3,
      fatigue: 48.1,
      headroom: -18.8,
    },
  ];

  const [fitness, fatigue, load] = seriesOf(loadOption(days));

  expect(fitness.data).toEqual([
    ["2026-10-01", 30],
    ["2026-10-02", 29.3],
  ]);
  expect(fatigue.data).toEqual([
    ["2026-10-01", 55.6],
    ["2026-10-02", 48.1],
  ]);
  expect(load.data).toEqual([
    ["2026-10-01", 42.4],
    ["2026-10-02", 0],
  ]);
});

test("負荷が null の日は棒を出さず、負荷 0 の高さに印を置く", () => {
  const days: DayPoint[] = [
    { day: "2026-10-01", load: null, fitness: 30, fatigue: 50, headroom: -20 },
    { day: "2026-10-02", load: 0, fitness: 29, fatigue: 45, headroom: -16 },
  ];

  const [, , load, noHeartRate] = seriesOf(loadOption(days));

  expect(load.data).toEqual([
    ["2026-10-01", null],
    ["2026-10-02", 0],
  ]);
  // 休養日（負荷 0）には印を置かない
  expect(noHeartRate.name).toBe("No heart rate");
  expect(noHeartRate.data).toEqual([["2026-10-01", 0]]);
});

test("心拍のない日がなければ、凡例に No heart rate を出さない", () => {
  const legendOf = (days: DayPoint[]) =>
    (loadOption(days).legend as { data: string[] }).data;
  const day = { fitness: 30, fatigue: 50, headroom: -20 };

  expect(legendOf([{ day: "2026-10-01", load: 12, ...day }])).toEqual([
    "Fitness",
    "Fatigue",
    "Load",
  ]);
  expect(legendOf([{ day: "2026-10-01", load: null, ...day }])).toContain(
    "No heart rate",
  );
});

test("VO2max は測定値と 30 日平均を別の series にする", () => {
  const points: Vo2MaxPoint[] = [
    { day: "2026-10-01", value: 48.24, average: 47.96 },
    { day: "2026-10-05", value: 49.1, average: 48.67 },
  ];

  const [value, average] = seriesOf(vo2maxOption(points));

  expect(value.data).toEqual([
    ["2026-10-01", 48.2],
    ["2026-10-05", 49.1],
  ]);
  expect(average.data).toEqual([
    ["2026-10-01", 48],
    ["2026-10-05", 48.7],
  ]);
});

test("強度ごとの時間は分に直し、低・中・高の順に並べる", () => {
  const [time] = seriesOf(zonesOption({ low: 3600, mid: 1530, high: 89 }));

  expect(time.data).toEqual([60, 26, 1]);
});

test("境目が未設定で zones が null なら、チャートを出さない", () => {
  expect(zonesOption(null)).toBeNull();
});

test("散布図は種目ごとに分け、負荷か高強度の時間が null の回は除く", () => {
  const workouts = [
    point({ id: 1, sport: "ride", load: 80.25, high_sec: 900 }),
    point({ id: 2, sport: "run", load: 60, high_sec: 1200 }),
    point({ id: 3, sport: "ride", load: null }),
    point({ id: 4, sport: "run", high_sec: null }),
  ];

  const [ride, run] = seriesOf(workoutsOption(workouts));

  expect(ride.name).toBe("Ride");
  expect(ride.data).toEqual([[80.3, 15]]);
  expect(run.name).toBe("Run");
  expect(run.data).toEqual([[60, 20]]);
});

test("記録がなければ、どのチャートも空の series になる", () => {
  expect(seriesOf(loadOption([])).map((s) => s.data)).toEqual([[], [], [], []]);
  expect(seriesOf(vo2maxOption([])).map((s) => s.data)).toEqual([[], []]);
  expect(seriesOf(workoutsOption([]))).toEqual([]);
});

function day(d: string, fitness: number, fatigue: number): DayPoint {
  return { day: d, load: 10, fitness, fatigue, headroom: fitness - fatigue };
}

function memo(date: string, label: string | null, body = "x"): NoteOut {
  return {
    id: 1,
    date,
    label,
    body,
    created_at: `${date}T12:00:00Z`,
    updated_at: `${date}T12:00:00Z`,
  };
}

type MarkPoint = {
  data: { name: string; coord: [string, number] }[];
  label: { formatter: string; backgroundColor: string };
};

function markPointOf(option: EChartsOption): MarkPoint | undefined {
  const [fitness] = seriesOf(option) as (SeriesOption & {
    markPoint?: MarkPoint;
  })[];
  return fitness.markPoint;
}

test("ラベルのあるメモの日に、体力と疲労の高いほうの 1.1 倍の高さで吹き出しを立てる", () => {
  const days = [day("2026-10-01", 30, 50), day("2026-10-02", 40, 20)];
  const notes = [memo("2026-10-01", "Race"), memo("2026-10-02", "大会")];

  const mark = markPointOf(loadOption(days, notes));

  expect(mark?.data).toEqual([
    { name: "Race", coord: ["2026-10-01", 55], value: "Race" },
    { name: "大会", coord: ["2026-10-02", 44], value: "大会" },
  ]);
  // 文字は吹き出しに重ね、はみ出しても読めるよう同じ色の帯を敷く
  expect(mark?.label.formatter).toBe("{b}");
  expect(mark?.label.backgroundColor).toBeTruthy();
});

test("ラベルのないメモと、チャートの期間の外のメモには印を出さない", () => {
  const days = [day("2026-10-01", 30, 50)];
  const notes = [memo("2026-10-01", null), memo("2026-09-01", "Old")];

  const option = loadOption(days, notes);

  expect(markPointOf(option)).toBeUndefined();
  // 印がない間は、軸の上の余白も足さない
  const [axis] = option.yAxis as { max?: unknown }[];
  expect(axis.max).toBeUndefined();
});

test("印がある間は、いちばん高い吹き出しの先から上に吹き出しの分を空ける", () => {
  const option = loadOption(
    [day("2026-10-01", 30, 50)],
    [memo("2026-10-01", "Race")],
  );

  // 先は 50 × 1.1 = 55。グリッドの高さ 150px のうち上の 42px を空けると 76.4、切り上げて 80
  const [axis] = option.yAxis as { max: (v: { max: number }) => number }[];
  expect(axis.max({ max: 50 })).toBe(80);
  // 実際に描いて収まるかは charts.render.test.ts で確かめる
});

test("軸の上端は、データの最大のほうが高ければそちらを使い、目盛りがそろうよう切り上げる", () => {
  expect(axisMaxForPins(200, 55)).toBe(200);
  expect(axisMaxForPins(203, 55)).toBe(210);
  // 50 未満は 5 刻み
  expect(axisMaxForPins(7, 7.7)).toBe(15);
});

test("吹き出しにはツールチップを出さず、軸のツールチップは標準の表示のまま", () => {
  const option = loadOption(
    [day("2026-10-01", 30, 50)],
    [memo("2026-10-01", "Race", "Hill climb")],
  );

  // ラベルは吹き出しの上に出ていて、本文はチャートの下の一覧で読める
  const [fitness] = seriesOf(option) as (SeriesOption & {
    markPoint?: { tooltip?: { show?: boolean } };
  })[];
  expect(fitness.markPoint?.tooltip?.show).toBe(false);
  expect(option.tooltip).toEqual({ trigger: "axis" });
});
