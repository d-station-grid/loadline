import { fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { WorkoutDetail } from "../api";
import { getNotes, getSettings, getWorkout } from "../lib/api";
import WorkoutPage from "./WorkoutPage";

vi.mock("../lib/api", () => ({
  getWorkout: vi.fn(),
  getSettings: vi.fn(),
  getNotes: vi.fn(),
}));

const user = { getIdToken: async () => "token" } as unknown as User;

const detail: WorkoutDetail = {
  id: 7,
  sport: "ride",
  started_at: "2026-09-13T05:10:45+00:00",
  ended_at: "2026-09-13T06:21:25+00:00",
  duration_sec: 4028,
  avg_heart_rate: 126,
  max_heart_rate: 174,
  heart_rates: [
    {
      recorded_at: "2026-09-13T05:10:00+00:00",
      min_bpm: 104,
      avg_bpm: 105,
      max_bpm: 107,
    },
    {
      recorded_at: "2026-09-13T05:11:00+00:00",
      min_bpm: 110,
      avg_bpm: 120,
      max_bpm: 130,
    },
    {
      recorded_at: "2026-09-13T05:12:00+00:00",
      min_bpm: 150,
      avg_bpm: 160,
      max_bpm: 170,
    },
  ],
  zones: { low: 60, mid: 60, high: 60 },
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSettings).mockResolvedValue({
    max_heart_rate: 185,
    resting_heart_rate: 52,
    zone_boundary_1: 148,
    zone_boundary_2: 166,
    timezone: "Asia/Tokyo",
    review_weekday: 0,
    send_notes_to_ai: true,
    ingest_token_last_four: null,
  });
  vi.mocked(getNotes).mockResolvedValue({ items: [] });
});

test("数値と心拍の推移と強度の内訳が出る", async () => {
  vi.mocked(getWorkout).mockResolvedValue(detail);
  render(<WorkoutPage user={user} workoutId={7} onBack={vi.fn()} />);

  expect(
    await screen.findByRole("heading", { name: "Ride" }),
  ).toBeInTheDocument();
  expect(screen.getByText("1h 07m")).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: "Heart rate over time" }),
  ).toBeInTheDocument();
  const zones = screen.getByRole("list", { name: "Time in each zone" });
  expect(zones).toHaveTextContent("Low1m33%");
  expect(getWorkout).toHaveBeenCalledWith(7, "token");
});

test("境目が未設定なら案内を出す", async () => {
  vi.mocked(getWorkout).mockResolvedValue({ ...detail, zones: null });
  render(<WorkoutPage user={user} workoutId={7} onBack={vi.fn()} />);

  expect(
    await screen.findByText(
      "Set your heart rate boundaries in Settings to see intensity.",
    ),
  ).toBeInTheDocument();
});

test("心拍がなければ、境目の案内ではなく心拍がないと出す", async () => {
  vi.mocked(getWorkout).mockResolvedValue({
    ...detail,
    heart_rates: [],
    zones: null,
  });
  render(<WorkoutPage user={user} workoutId={7} onBack={vi.fn()} />);

  expect(
    await screen.findByText("No heart rate data for this workout."),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(
      "Set your heart rate boundaries in Settings to see intensity.",
    ),
  ).not.toBeInTheDocument();
});

test("戻るボタンで onBack を呼ぶ", async () => {
  vi.mocked(getWorkout).mockResolvedValue(detail);
  const onBack = vi.fn();
  render(<WorkoutPage user={user} workoutId={7} onBack={onBack} />);

  fireEvent.click(await screen.findByRole("button", { name: "‹ Workouts" }));

  expect(onBack).toHaveBeenCalled();
});

test("api が失敗したらエラーと戻るボタンを出す", async () => {
  vi.mocked(getWorkout).mockRejectedValue(new Error("API returned 404"));
  render(<WorkoutPage user={user} workoutId={7} onBack={vi.fn()} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 404",
  );
  expect(
    screen.getByRole("button", { name: "‹ Workouts" }),
  ).toBeInTheDocument();
});

test("強度の境目を点線で引き、その日のメモを利用者のタイムゾーンの日付で読む", async () => {
  vi.mocked(getWorkout).mockResolvedValue(detail);
  vi.mocked(getNotes).mockResolvedValue({
    items: [
      {
        id: 1,
        date: "2026-09-13",
        label: "Hill ride",
        body: "Rode the hill route.",
      },
    ],
  } as Awaited<ReturnType<typeof getNotes>>);
  render(<WorkoutPage user={user} workoutId={7} onBack={vi.fn()} />);

  expect(await screen.findByText("Rode the hill route.")).toBeInTheDocument();
  expect(screen.getByText("Low | Mid 148")).toBeInTheDocument();
  expect(screen.getByText("Mid | High 166")).toBeInTheDocument();
  // 9/13 05:10 UTC は東京でも 9/13
  expect(getNotes).toHaveBeenCalledWith(
    { since: "2026-09-13", until: "2026-09-14" },
    "token",
  );
});

test("設定が読めなくても、詳細は出す", async () => {
  vi.mocked(getWorkout).mockResolvedValue(detail);
  vi.mocked(getSettings).mockRejectedValue(new Error("API returned 500"));
  render(<WorkoutPage user={user} workoutId={7} onBack={vi.fn()} />);

  expect(
    await screen.findByRole("heading", { name: "Ride" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText(/Low \| Mid/)).toBeNull();
});
