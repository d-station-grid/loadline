import { fireEvent, render, screen, within } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { Dashboard, WorkoutSummary } from "../api";
import { getDashboard, getWorkouts } from "../lib/api";
import DashboardPage from "./DashboardPage";

vi.mock("../lib/api", () => ({ getDashboard: vi.fn(), getWorkouts: vi.fn() }));
// 振り返り、メモ、チャートは、それぞれのテストで見る。ここでは読み方と表だけを見る
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

  // 読み直すのは上の All だけ。Intensity（12 週）は持っている結果を使う
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

  // 上の 4 週の読み込みは終わらせない
  vi.mocked(getDashboard).mockReturnValue(new Promise(() => {}));
  const period = screen.getByRole("group", { name: "Period" });
  fireEvent.click(within(period).getByRole("button", { name: "4 weeks" }));

  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2));
  expect(vi.mocked(getDashboard).mock.calls[1][0]).toMatchObject({ weeks: 4 });
  // Intensity（12 週）は前の結果のまま
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
  fireEvent.click(within(period).getByRole("button", { name: "4 weeks" }));
  await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2));
  fireEvent.click(within(period).getByRole("button", { name: "12 weeks" }));

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
