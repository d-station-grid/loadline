import type { EChartsOption, SeriesOption } from "echarts";
import { expect, test } from "vitest";

import type { DayPoint, NoteOut, Vo2MaxPoint, WorkoutPoint } from "../api";
import {
  loadOption,
  trendOption,
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

type MarkLine = {
  data: { name: string; xAxis: string }[];
  label: { show: boolean; formatter?: string };
  lineStyle: { type: string };
};

function markLineOf(option: EChartsOption, index = 0): MarkLine | undefined {
  const series = seriesOf(option) as (SeriesOption & {
    markLine?: MarkLine;
  })[];
  return series[index].markLine;
}

test("ラベルのあるメモの日に、縦の点線とラベルを出す", () => {
  const days = [day("2026-10-01", 30, 50), day("2026-10-02", 40, 20)];
  const notes = [memo("2026-10-01", "Race"), memo("2026-10-02", "大会")];

  const line = markLineOf(loadOption(days, notes));

  expect(line?.data).toEqual([
    { name: "Race", xAxis: "2026-10-01" },
    { name: "大会", xAxis: "2026-10-02" },
  ]);
  expect(line?.lineStyle.type).toBe("dashed");
  expect(line?.label).toMatchObject({ show: true, formatter: "{b}" });
});

test("ラベルのないメモと、チャートの期間の外のメモには線を出さない", () => {
  const days = [day("2026-10-01", 30, 50)];
  const notes = [memo("2026-10-01", null), memo("2026-09-01", "Old")];

  expect(markLineOf(loadOption(days, notes))).toBeUndefined();
});

const period = { since: "2026-10-01", until: "2026-10-02" };

test("上下 2 段のチャートは、上に体力・疲労・負荷、下に VO2max を置き、横の期間をそろえる", () => {
  const option = trendOption(
    [day("2026-10-01", 30, 50), day("2026-10-02", 31, 45)],
    [{ day: "2026-10-02", value: 48, average: 47.5 }],
    [],
    period,
  );

  const series = seriesOf(option) as (SeriesOption & {
    xAxisIndex?: number;
    yAxisIndex?: number;
  })[];
  expect(series.map((s) => s.name)).toEqual([
    "Fitness",
    "Fatigue",
    "Load",
    "No heart rate",
    "VO2max",
    "30-day average",
    undefined, // 下の段の日付を上の段とそろえる見えない棒
  ]);
  // VO2max は下の段の軸に載せる
  expect(series[4]).toMatchObject({ xAxisIndex: 1, yAxisIndex: 2 });
  // 横の軸は 2 本とも api の期間にする。日付の位置がそろう
  for (const axis of option.xAxis as object[]) {
    expect(axis).toMatchObject({
      type: "time",
      min: "2026-10-01",
      max: "2026-10-02",
    });
  }
  // 凡例は上下ぶんをまとめる。心拍のない日がなければ No heart rate は出さない
  expect((option.legend as { data: string[] }).data).toEqual([
    "Fitness",
    "Fatigue",
    "Load",
    "VO2max",
    "30-day average",
  ]);
});

test("メモの点線は下の段にも引き、ラベルは上の段だけに出す", () => {
  const option = trendOption(
    [day("2026-10-01", 30, 50)],
    [],
    [memo("2026-10-01", "Race")],
    period,
  );

  expect(markLineOf(option, 0)?.label.show).toBe(true);
  const bottom = markLineOf(option, 4);
  expect(bottom?.data).toEqual([{ name: "Race", xAxis: "2026-10-01" }]);
  expect(bottom?.label.show).toBe(false);
});

test("心拍の設定がなく days が空なら、VO2max の段だけにする", () => {
  const option = trendOption(
    [],
    [{ day: "2026-10-02", value: 48, average: 47.5 }],
    [],
    period,
  );

  expect(seriesOf(option).map((s) => s.name)).toEqual([
    "VO2max",
    "30-day average",
  ]);
  expect(option.xAxis).toMatchObject({ min: "2026-10-01", max: "2026-10-02" });
});

test("時間の軸は、重なった日付の文字を間引く", () => {
  // 月の頭の「Oct」と近くの日付の目盛りが重なって「29Oct」のように読めるため
  for (const option of [loadOption([], []), vo2maxOption([])]) {
    expect(option.xAxis).toMatchObject({
      type: "time",
      axisLabel: { hideOverlap: true },
    });
  }
});
