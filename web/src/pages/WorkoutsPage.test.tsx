import { act, fireEvent, render, screen } from "@testing-library/react";
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
  // 始まりの日は api が決める。画面は週の数だけ渡す
  expect(first.weeks).toBe(4);
  expect(first.since).toBeUndefined();

  fireEvent.click(screen.getByRole("button", { name: "All" }));

  await vi.waitFor(() => expect(getWorkouts).toHaveBeenCalledTimes(2));
  const second = vi.mocked(getWorkouts).mock.calls[1][0];
  expect(second.weeks).toBeUndefined();
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
  expect(second.before_id).toBe(firstPage[99].id);
  expect(second.weeks).toBe(4);
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

test("選択中の期間をもう一度押しても、一覧は消えず読み直さない", async () => {
  vi.mocked(getWorkouts).mockResolvedValue({ items: [ride] });
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);
  await screen.findByRole("button", { name: "Ride" });

  fireEvent.click(screen.getByRole("button", { name: "Last 4 weeks" }));

  expect(screen.getByRole("button", { name: "Ride" })).toBeInTheDocument();
  expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  expect(getWorkouts).toHaveBeenCalledTimes(1);
});

test("Load more を待つ間に期間を変えたら、遅れて届いた応答は捨てる", async () => {
  let resolveMore: (list: { items: WorkoutSummary[] }) => void = () => {};
  const more = new Promise<{ items: WorkoutSummary[] }>((resolve) => {
    resolveMore = resolve;
  });
  vi.mocked(getWorkouts)
    .mockResolvedValueOnce({ items: rides(100) }) // 4 週の 1 ページ目
    .mockReturnValueOnce(more) // 4 週の Load more（遅い）
    .mockResolvedValueOnce({ items: [ride] }); // All の 1 ページ目
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
  fireEvent.click(screen.getByRole("button", { name: "All" }));
  await vi.waitFor(() => expect(getWorkouts).toHaveBeenCalledTimes(3));
  await vi.waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(2));

  await act(async () => {
    resolveMore({ items: rides(3, 100) });
    await more;
  });

  // 遅れた応答が届いても、All の 1 件のまま
  expect(screen.getAllByRole("row")).toHaveLength(2);
  expect(
    screen.queryByRole("button", { name: "Load more" }),
  ).not.toBeInTheDocument();
});

test("別の期間に行って同じ期間に戻ったあと、遅れて届いた古い Load more の応答は捨てる", async () => {
  let resolveThird: (list: { items: WorkoutSummary[] }) => void = () => {};
  const third = new Promise<{ items: WorkoutSummary[] }>((resolve) => {
    resolveThird = resolve;
  });
  vi.mocked(getWorkouts)
    .mockResolvedValueOnce({ items: rides(100) }) // 4 週の 1 ページ目
    .mockResolvedValueOnce({ items: rides(100, 100) }) // 4 週の 2 ページ目
    .mockReturnValueOnce(third) // 4 週の 3 ページ目（遅い）
    .mockResolvedValueOnce({ items: [ride] }) // All の 1 ページ目
    .mockResolvedValueOnce({ items: rides(100) }); // 4 週に戻った 1 ページ目
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
  await vi.waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(201));
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  await vi.waitFor(() => expect(getWorkouts).toHaveBeenCalledTimes(3));

  fireEvent.click(screen.getByRole("button", { name: "All" }));
  await vi.waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "Last 4 weeks" }));
  await vi.waitFor(() => expect(getWorkouts).toHaveBeenCalledTimes(5));
  await vi.waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(101));

  await act(async () => {
    resolveThird({ items: rides(3, 200) });
    await third;
  });

  // 戻った 4 週の 1 ページ目のままで、古い 3 ページ目は足されない。Load more は押せる
  expect(screen.getAllByRole("row")).toHaveLength(101);
  expect(screen.getByRole("button", { name: "Load more" })).toBeEnabled();
});

test("Load more を連打しても、同じページは一度しか足さない", async () => {
  let resolveMore: (list: { items: WorkoutSummary[] }) => void = () => {};
  const more = new Promise<{ items: WorkoutSummary[] }>((resolve) => {
    resolveMore = resolve;
  });
  vi.mocked(getWorkouts)
    .mockResolvedValueOnce({ items: rides(100) })
    .mockReturnValue(more);
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);

  const button = await screen.findByRole("button", { name: "Load more" });
  // 1 つの act にまとめ、描画（disabled）の前に 2 回目のクリックが届く形にする
  act(() => {
    button.click();
    button.click();
  });

  await act(async () => {
    resolveMore({ items: rides(3, 100) });
    await more;
  });

  expect(getWorkouts).toHaveBeenCalledTimes(2);
  expect(screen.getAllByRole("row")).toHaveLength(104);
});

test("api が失敗したらエラーを出し、Retry で同じ期間を取り直す", async () => {
  vi.mocked(getWorkouts)
    .mockRejectedValueOnce(new Error("API returned 500"))
    .mockResolvedValueOnce({ items: [ride] });
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );

  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  await screen.findByRole("button", { name: "Ride" });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(vi.mocked(getWorkouts).mock.calls[1][0].weeks).toBe(4);
});

test("失敗のあと別の期間が取れたら、エラーは消える", async () => {
  vi.mocked(getWorkouts)
    .mockRejectedValueOnce(new Error("API returned 500"))
    .mockResolvedValueOnce({ items: [ride] });
  render(<WorkoutsPage user={user} onSelect={vi.fn()} />);
  await screen.findByRole("alert");

  fireEvent.click(screen.getByRole("button", { name: "All" }));

  await screen.findByRole("button", { name: "Ride" });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
