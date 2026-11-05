import { fireEvent, render, screen, within } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { Dashboard, WorkoutSummary } from "../api";
import { getDashboard, getWorkouts } from "../lib/api";
import DashboardPage from "./DashboardPage";

vi.mock("../lib/api", () => ({ getDashboard: vi.fn(), getWorkouts: vi.fn() }));
// 振り返り、メモ、チャートは、それぞれのテストで見る。ここでは読み方と表だけを見る
vi.mock("../components/Review", () => ({ default: () => null }));
vi.mock("../components/Notes", () => ({ default: () => null }));
vi.mock("../components/Chart", () => ({ default: () => null }));

const user = { getIdToken: async () => "token" } as unknown as User;

function dashboard(workouts: Dashboard["workouts"]): Dashboard {
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
  fireEvent.click(within(period).getByRole("button", { name: "All" }));

  // 上の期間が All になり、Intensity（12 週）とは条件が分かれるので、2 つとも読み直す
  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(3));
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
