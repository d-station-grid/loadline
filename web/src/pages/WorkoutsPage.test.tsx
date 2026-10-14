import { fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { WorkoutSummary } from "../api";
import { getWorkouts } from "../lib/api";
import WorkoutsPage from "./WorkoutsPage";

vi.mock("../lib/api", () => ({ getWorkouts: vi.fn() }));

const user = { getIdToken: async () => "token" } as unknown as User;

const ride: WorkoutSummary = {
  id: 7,
  sport: "ride",
  started_at: "2026-09-13T05:10:45+00:00",
  ended_at: "2026-09-13T06:21:25+00:00",
  duration_sec: 4028,
  avg_heart_rate: 126,
  max_heart_rate: 174,
};

beforeEach(() => {
  vi.clearAllMocks();
});

test("一覧に種目、時間、心拍が出て、押すと id を知らせる", async () => {
  vi.mocked(getWorkouts).mockResolvedValue({ items: [ride] });
  const onSelect = vi.fn();
  render(<WorkoutsPage user={user} onSelect={onSelect} />);

  const button = await screen.findByRole("button", { name: "Ride" });
  expect(screen.getByText("1h 07m")).toBeInTheDocument();
  expect(screen.getByText("126")).toBeInTheDocument();
  expect(screen.getByText("174")).toBeInTheDocument();

  fireEvent.click(button);

  expect(onSelect).toHaveBeenCalledWith(7);
});

test("既定は直近 4 週で、期間を変えると読み直す", async () => {
  vi.mocked(getWorkouts).mockResolvedValue({ items: [] });
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);
  await screen.findByText("No workouts in this period.");

  const first = vi.mocked(getWorkouts).mock.calls[0][0];
  expect(first.since).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: "All" }));

  await vi.waitFor(() => expect(getWorkouts).toHaveBeenCalledTimes(2));
  const second = vi.mocked(getWorkouts).mock.calls[1][0];
  expect(second.since).toBeUndefined();
  expect(screen.getByRole("button", { name: "All" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

/** id と started_at だけ変えた ride を n 件。新しい順に並べる。 */
function rides(n: number, from = 0): WorkoutSummary[] {
  return Array.from({ length: n }, (_, i) => {
    const day = String(28 - ((from + i) % 28)).padStart(2, "0");
    const month = String(9 - Math.floor((from + i) / 28)).padStart(2, "0");
    return {
      ...ride,
      id: 1000 - from - i,
      started_at: `2026-${month}-${day}T05:10:45+00:00`,
    };
  });
}

test("100 件返ってきたら Load more を出し、押すと一番古い記録より前を足す", async () => {
  const firstPage = rides(100);
  const secondPage = rides(3, 100);
  vi.mocked(getWorkouts)
    .mockResolvedValueOnce({ items: firstPage })
    .mockResolvedValueOnce({ items: secondPage });
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);

  const more = await screen.findByRole("button", { name: "Load more" });
  expect(screen.getAllByRole("row")).toHaveLength(101); // 見出し 1 行 + 100 件

  fireEvent.click(more);

  await vi.waitFor(() => expect(getWorkouts).toHaveBeenCalledTimes(2));
  const second = vi.mocked(getWorkouts).mock.calls[1][0];
  expect(second.until).toBe(firstPage[99].started_at);
  expect(second.since).toBe(vi.mocked(getWorkouts).mock.calls[0][0].since);
  await vi.waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(104));
  expect(
    screen.queryByRole("button", { name: "Load more" }),
  ).not.toBeInTheDocument();
});

test("100 件未満なら Load more は出ない", async () => {
  vi.mocked(getWorkouts).mockResolvedValue({ items: [ride] });
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);
  await screen.findByRole("button", { name: "Ride" });

  expect(
    screen.queryByRole("button", { name: "Load more" }),
  ).not.toBeInTheDocument();
});

test("api が失敗したらエラーを出す", async () => {
  vi.mocked(getWorkouts).mockRejectedValue(new Error("API returned 500"));
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
});
