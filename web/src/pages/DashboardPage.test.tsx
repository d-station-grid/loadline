import { fireEvent, render, screen, within } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { Dashboard, WorkoutSummary } from "../api";
import { getDashboard, getWorkouts } from "../lib/api";
import { formatDay } from "../lib/format";
import DashboardPage from "./DashboardPage";

vi.mock("../lib/api", () => ({ getDashboard: vi.fn(), getWorkouts: vi.fn() }));
// 週次レビュー、メモ、チャートは、それぞれのテストで見る。ここでは読み方と表だけを見る
vi.mock("../components/Review", () => ({ default: () => null }));
vi.mock("../components/Notes", () => ({
  default: ({ pick }: { pick?: { date: string } }) => (
    <>
      <p>notes for {pick?.date ?? "none"}</p>
      <button type="button">Add</button>
    </>
  ),
}));
vi.mock("../components/Chart", () => ({ default: () => null }));

const user = { getIdToken: async () => "token" } as unknown as User;

function dashboard(
  workouts: Dashboard["workouts"],
  extra: Partial<Dashboard> = {},
): Dashboard {
  return {
    since: "2026-08-10",
    until: "2026-11-01",
    sport: "all",
    needs_heart_rate_settings: false,
    days: [
      {
        day: "2026-11-01",
        load: 50,
        fitness: 54.6,
        fatigue: 68.8,
        headroom: -0.04,
      },
    ],
    vo2max: [{ day: "2026-10-26", value: 48.7, average: 48.5 }],
    zones: { low: 3600, mid: 1800, high: 600 },
    workouts,
    changes: {
      fitness: 5,
      fatigue: 5,
      headroom: 0,
      vo2max: 0.1,
      vo2max_since: "2026-09-20",
    },
    form: "steady",
    zone_weeks: [],
    totals: {
      start: "2026-08-10",
      end: "2026-11-01",
      workouts: workouts.length,
      total_sec: 3600 * workouts.length,
      load: null,
      load_per_workout: null,
      workouts_without_load: 0,
    },
    previous_totals: {
      start: "2026-05-18",
      end: "2026-08-09",
      workouts: 0,
      total_sec: 0,
      load: 0,
      load_per_workout: null,
      workouts_without_load: 0,
    },
    last_received_at: null,
    ...extra,
  };
}

function summary(id: number, sport: string): WorkoutSummary {
  return {
    id,
    sport,
    started_at: "2026-11-01T05:00:00+00:00",
    ended_at: "2026-11-01T06:00:00+00:00",
    duration_sec: 3600,
    avg_heart_rate: 130,
    max_heart_rate: 170,
  };
}

function point(id: number, load: number | null) {
  return {
    id,
    sport: "ride",
    started_at: "2026-11-01T05:00:00+00:00",
    day: "2026-11-01",
    load,
    high_sec: 60,
  };
}

const props = {
  user,
  onOpenSettings: vi.fn(),
  onOpenWorkouts: vi.fn(),
  onOpenWorkout: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

test("上の期間と Intensity が同じ条件の間は、GET /dashboard を 1 回だけ読む", async () => {
  vi.mocked(getDashboard).mockResolvedValue(dashboard([point(1, 50)]));
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);

  await screen.findByText("Time in each zone");
  expect(getDashboard).toHaveBeenCalledTimes(1);

  // Intensity の種目を変えると、その条件で別に読む
  const sport = screen.getByRole("group", { name: "Intensity sport" });
  fireEvent.click(within(sport).getByRole("button", { name: "Ride" }));

  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2));
  expect(vi.mocked(getDashboard).mock.calls[1][0]).toMatchObject({
    sport: "ride",
  });
});

test("期間を切り替えて読み込み直す間も、Recent workouts の負荷を出し続ける", async () => {
  vi.mocked(getDashboard).mockResolvedValueOnce(dashboard([point(1, 82)]));
  vi.mocked(getWorkouts).mockResolvedValue({
    since: null,
    items: [summary(1, "ride")],
  });
  render(<DashboardPage {...props} />);
  await screen.findByText("82");

  // 次の読み込みは終わらせない
  vi.mocked(getDashboard).mockReturnValue(new Promise(() => {}));
  const period = screen.getByRole("group", { name: "Period" });
  fireEvent.click(within(period).getByRole("button", { name: "6M" }));

  // 読み直すのは上の 6M だけ。Intensity（3M）は持っている結果を使う
  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2));
  expect(screen.getByText("82")).toBeInTheDocument();
});

test("負荷は、心拍のない回を No HR、期間の外の回を – と分けて出す", async () => {
  vi.mocked(getDashboard).mockResolvedValue(dashboard([point(1, null)]));
  vi.mocked(getWorkouts).mockResolvedValue({
    since: null,
    items: [summary(1, "ride"), summary(2, "run")],
  });
  render(<DashboardPage {...props} />);

  expect(await screen.findByText("No HR")).toBeInTheDocument();
  expect(screen.getByTitle("Outside the dashboard period")).toHaveTextContent(
    "–",
  );
});

test("数字のカードは小数 1 桁で、0 に近い負の値を -0.0 と出さない。VO2max には測った日を添える", async () => {
  vi.mocked(getDashboard).mockResolvedValue(dashboard([]));
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);

  const stats = await screen.findByLabelText("Latest");
  expect(within(stats).getByText("54.6")).toBeInTheDocument();
  expect(within(stats).getByText("0.0")).toBeInTheDocument();
  expect(within(stats).queryByText("-0.0")).toBeNull();
  expect(within(stats).getByText(/26/)).toBeInTheDocument();
});

test("上の期間だけを変えても、Intensity は持っている結果を使い、Loading にならず読み直さない", async () => {
  vi.mocked(getDashboard).mockResolvedValue(dashboard([point(1, 50)]));
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);
  await screen.findByText("Time in each zone");
  expect(getDashboard).toHaveBeenCalledTimes(1);

  // 上の 1M（4 週）の読み込みは終わらせない
  vi.mocked(getDashboard).mockReturnValue(new Promise(() => {}));
  const period = screen.getByRole("group", { name: "Period" });
  fireEvent.click(within(period).getByRole("button", { name: "1M" }));

  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2));
  expect(vi.mocked(getDashboard).mock.calls[1][0]).toMatchObject({ weeks: 4 });
  // Intensity（3M）は前の結果のまま
  expect(screen.getByText("Time in each zone")).toBeInTheDocument();
  const card = screen.getByRole("region", { name: "Intensity" });
  expect(within(card).queryByText("Loading…")).toBeNull();
});

test("前に読んだ期間に戻したときは、読み直さない", async () => {
  vi.mocked(getDashboard).mockResolvedValue(dashboard([point(1, 50)]));
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);
  await screen.findByText("Time in each zone");

  const period = screen.getByRole("group", { name: "Period" });
  fireEvent.click(within(period).getByRole("button", { name: "1M" }));
  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2));
  fireEvent.click(within(period).getByRole("button", { name: "3M" }));

  await screen.findByText("Fitness, fatigue and VO2max");
  expect(getDashboard).toHaveBeenCalledTimes(2);
});

test("「+ Note」でメモのモーダルを今日の日で開き、Esc と Close で閉じる", async () => {
  vi.mocked(getDashboard).mockResolvedValue(dashboard([]));
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);

  // 閉じている間も中身は外さず、隠すだけ
  await screen.findByText("Fitness, fatigue and VO2max");
  expect(screen.queryByRole("dialog")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "+ Note" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("notes for 2026-11-01")).toBeInTheDocument();

  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "+ Note" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }),
  );
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("メモのモーダルは Tab を中で回し、外にフォーカスがあっても Esc で閉じ、開いたボタンに戻す", async () => {
  vi.mocked(getDashboard).mockResolvedValue(dashboard([]));
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);
  await screen.findByText("Fitness, fatigue and VO2max");

  const opener = screen.getByRole("button", { name: "+ Note" });
  opener.focus();
  fireEvent.click(opener);
  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveFocus();

  // 最後の Close から Tab で先頭に、先頭から Shift+Tab で Close に回る
  const add = within(dialog).getByRole("button", { name: "Add" });
  const close = within(dialog).getByRole("button", { name: "Close" });
  close.focus();
  fireEvent.keyDown(close, { key: "Tab" });
  expect(add).toHaveFocus();
  fireEvent.keyDown(add, { key: "Tab", shiftKey: true });
  expect(close).toHaveFocus();

  // フォーカスがモーダルの外に出ていても、Esc で閉じる
  (document.activeElement as HTMLElement).blur();
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(opener).toHaveFocus();
});

test("カードの下に、api の差と Form の一言を出す。VO2max は比べた測定の日からの差と測った日", async () => {
  vi.mocked(getDashboard).mockResolvedValue(
    dashboard([], {
      changes: {
        fitness: 5,
        fatigue: -1.24,
        headroom: 6.2,
        vo2max: 0.1,
        vo2max_since: "2026-08-20",
      },
      form: "fatigued",
    }),
  );
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);

  const stats = await screen.findByLabelText("Latest");
  expect(within(stats).getByText("+5.0 vs last week")).toBeInTheDocument();
  expect(within(stats).getByText("-1.2 vs last week")).toBeInTheDocument();
  expect(within(stats).getByText("Tired — ease off")).toBeInTheDocument();
  // 測定が空くと 4 週より前と比べるので、「in 4 weeks」ではなく比べた日を書く
  expect(
    within(stats).getByText(
      `+0.1 since ${formatDay("2026-08-20")} · ${formatDay("2026-10-26")}`,
    ),
  ).toBeInTheDocument();
  expect(within(stats).queryByText(/in 4 weeks/)).toBeNull();
});

test("比べる値がなければ、差の行を出さない。VO2max は測った日だけ", async () => {
  vi.mocked(getDashboard).mockResolvedValue(
    dashboard([], {
      changes: {
        fitness: null,
        fatigue: null,
        headroom: null,
        vo2max: null,
        vo2max_since: null,
      },
      form: null,
    }),
  );
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);

  const stats = await screen.findByLabelText("Latest");
  expect(within(stats).queryByText(/vs last week/)).toBeNull();
  expect(within(stats).queryByText(/since/)).toBeNull();
  expect(within(stats).getByText(/26/)).toBeInTheDocument();
});

test("Last received は、取り込みが成功していれば見出しの横に出し、null なら出さない", async () => {
  vi.mocked(getDashboard).mockResolvedValueOnce(dashboard([]));
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  const { unmount } = render(<DashboardPage {...props} />);
  await screen.findByLabelText("Latest");
  expect(screen.queryByText(/Last received/)).toBeNull();
  unmount();

  vi.mocked(getDashboard).mockResolvedValueOnce(
    dashboard([], { last_received_at: "2026-09-24T07:12:00+09:00" }),
  );
  render(<DashboardPage {...props} />);
  expect(await screen.findByText(/^Last received · /)).toBeInTheDocument();
});

test("期間は 1W・1M・3M・6M で、最初は 3M（13 週）。選んだ期間の週の数を渡す", async () => {
  vi.mocked(getDashboard).mockResolvedValue(dashboard([point(1, 50)]));
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);
  await screen.findByText("Time in each zone");

  const period = screen.getByRole("group", { name: "Period" });
  expect(
    within(period)
      .getAllByRole("button")
      .map((b) => b.textContent),
  ).toEqual(["1W", "1M", "3M", "6M"]);
  expect(vi.mocked(getDashboard).mock.calls[0][0]).toMatchObject({
    weeks: 13,
  });

  fireEvent.click(within(period).getByRole("button", { name: "1W" }));
  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2));
  expect(vi.mocked(getDashboard).mock.calls[1][0]).toMatchObject({ weeks: 1 });

  fireEvent.click(within(period).getByRole("button", { name: "6M" }));
  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(3));
  expect(vi.mocked(getDashboard).mock.calls[2][0]).toMatchObject({
    weeks: 26,
  });
});

test("Totals は api の値を出す。負荷の 0 と分からない（–）を分け、前の期間を添える", async () => {
  vi.mocked(getDashboard).mockResolvedValue(
    dashboard([point(1, null)], {
      totals: {
        start: "2026-08-03",
        end: "2026-11-01",
        workouts: 2,
        total_sec: 5400,
        load: null,
        load_per_workout: null,
        workouts_without_load: 2,
      },
      previous_totals: {
        start: "2026-05-04",
        end: "2026-08-02",
        workouts: 0,
        total_sec: 0,
        load: 0,
        load_per_workout: null,
        workouts_without_load: 0,
      },
    }),
  );
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);

  const totals = await screen.findByLabelText("Totals");
  const tile = (label: string) =>
    within(totals).getByText(label).parentElement as HTMLElement;
  expect(tile("Time")).toHaveTextContent("1.5 h");
  expect(tile("Time")).toHaveTextContent("prev 3 months · 0.0 h");
  expect(tile("Workouts")).toHaveTextContent("2prev 3 months · 0");
  expect(tile("Load")).toHaveTextContent("–prev 3 months · 0");
  expect(tile("Load per workout")).toHaveTextContent("–prev 3 months · –");
  expect(
    screen.getByText(/Load leaves out workouts without heart rate: 2/),
  ).toBeInTheDocument();
  // 右上に種目、期間、回数
  expect(screen.getByText("All · last 3 months · 2")).toBeInTheDocument();
});

test("週ごとの強度は、心拍のない回を含む週を注記し、境目がなければ案内を出す", async () => {
  const week = (without: number) => ({
    start: "2026-10-26",
    end: "2026-11-01",
    zones: { low: 0, mid: 0, high: 0 },
    workouts_without_zones: without,
  });
  vi.mocked(getDashboard).mockResolvedValueOnce(
    dashboard([point(1, 50)], { zone_weeks: [week(0), week(1)] }),
  );
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  const { unmount } = render(<DashboardPage {...props} />);
  expect(
    await screen.findByText(/▲ marks 1 week\(s\) with a workout/),
  ).toBeInTheDocument();
  unmount();

  vi.mocked(getDashboard).mockResolvedValueOnce(
    dashboard([point(1, 50)], { zone_weeks: null }),
  );
  render(<DashboardPage {...props} />);
  expect(
    await screen.findByText("Needs zone boundaries in settings."),
  ).toBeInTheDocument();
});

test("境目があって期間の合計が出ないときは、心拍のない回の数だけを書く", async () => {
  vi.mocked(getDashboard).mockResolvedValue(
    dashboard([point(1, 50)], {
      zones: null,
      zone_weeks: [
        {
          start: "2026-10-19",
          end: "2026-10-25",
          zones: { low: 600, mid: 0, high: 0 },
          workouts_without_zones: 1,
        },
        {
          start: "2026-10-26",
          end: "2026-11-01",
          zones: { low: 0, mid: 0, high: 0 },
          workouts_without_zones: 2,
        },
      ],
    }),
  );
  vi.mocked(getWorkouts).mockResolvedValue({ since: null, items: [] });
  render(<DashboardPage {...props} />);

  expect(
    await screen.findByText(
      "Not shown: 3 workout(s) in this period have no heart rate.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Needs zone boundaries/)).toBeNull();
});
