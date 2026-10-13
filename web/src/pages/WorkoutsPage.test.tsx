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

test("api が失敗したらエラーを出す", async () => {
  vi.mocked(getWorkouts).mockRejectedValue(new Error("API returned 500"));
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
});
