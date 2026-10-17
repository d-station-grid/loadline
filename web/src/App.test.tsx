import { act, fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { UserOut } from "./api";
import App from "./App";
import { login } from "./lib/api";

const firebaseAuth = vi.hoisted(() => ({
  onAuthStateChanged: vi.fn(),
  signInWithPopup: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("firebase/auth", () => firebaseAuth);
vi.mock("./lib/firebase", () => ({ auth: {}, googleProvider: {} }));
vi.mock("./lib/api", () => ({ login: vi.fn() }));
// 設定ページは自分のテストで見る。ここではログインの流れだけ
vi.mock("./pages/SettingsPage", () => ({ default: () => <p>settings</p> }));
vi.mock("./pages/WorkoutsPage", () => ({ default: () => <p>workouts</p> }));
vi.mock("./pages/WorkoutPage", () => ({ default: () => <p>workout</p> }));
vi.mock("./pages/DashboardPage", () => ({
  default: ({ onOpenSettings }: { onOpenSettings: () => void }) => (
    <button type="button" onClick={onOpenSettings}>
      dashboard
    </button>
  ),
}));

/** Firebase からの通知を起こす。テストの途中でログインを起こすときにも使う。 */
let notify: (user: User | null) => void = () => {};

/** Firebase が復元するログイン状態を決める。null なら未ログイン。 */
function restoredUser(user: User | null) {
  firebaseAuth.onAuthStateChanged.mockImplementation(
    (_auth: unknown, next: (user: User | null) => void) => {
      notify = next;
      next(user);
      return () => {};
    },
  );
}

const taro = {
  displayName: "Taro",
  email: "taro@example.com",
  getIdToken: async () => "token",
} as unknown as User;

beforeEach(() => {
  vi.clearAllMocks();
  // Google のポップアップが通ると、Firebase はログイン済みの通知を出す
  firebaseAuth.signInWithPopup.mockImplementation(async () => {
    notify(taro);
    return { user: taro };
  });
});

test("未ログインならログインのボタンが出る", () => {
  restoredUser(null);
  render(<App />);
  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeInTheDocument();
});

test("復元した利用者を api に登録してから、名前とメールが出る", async () => {
  restoredUser(taro);
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  render(<App />);

  expect(await screen.findByText("Signed in as Taro")).toBeInTheDocument();
  expect(screen.getByText("taro@example.com")).toBeInTheDocument();
  expect(login).toHaveBeenCalledWith("token");
});

test("ボタンを押すと Google でログインし、api に登録してから名前が出る", async () => {
  restoredUser(null);
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: "Sign in with Google" }));

  expect(await screen.findByText("Signed in as Taro")).toBeInTheDocument();
  expect(login).toHaveBeenCalledWith("token");
  expect(firebaseAuth.signOut).not.toHaveBeenCalled();
});

test("api で失敗したらログアウトしてエラーを出す", async () => {
  restoredUser(null);
  vi.mocked(login).mockRejectedValue(new Error("API returned 500"));
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: "Sign in with Google" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
  expect(firebaseAuth.signOut).toHaveBeenCalled();
  expect(screen.queryByText("Signed in as Taro")).not.toBeInTheDocument();
});

test("api の応答待ちの間にログアウトされたら、古い処理は画面を戻さない", async () => {
  let finishLogin: (user: UserOut) => void = () => {};
  vi.mocked(login).mockImplementation(
    () => new Promise<UserOut>((resolve) => (finishLogin = resolve)),
  );
  restoredUser(taro);
  render(<App />);

  // 応答を待っている間に、別タブのログアウトで null の通知が来る
  await act(async () => {
    notify(null);
  });
  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeInTheDocument();

  // そのあとで api が成功しても、ログイン済みには戻らない
  await act(async () => {
    finishLogin({ id: 1, email: "taro@example.com" });
  });
  expect(screen.queryByText("Signed in as Taro")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeInTheDocument();
});

test("ログイン後の最初の画面はダッシュボードで、ヘッダーから移れる", async () => {
  restoredUser(taro);
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  render(<App />);

  expect(
    await screen.findByRole("button", { name: "dashboard" }),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Workouts" }));
  expect(
    screen.queryByRole("button", { name: "dashboard" }),
  ).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Dashboard" }));
  expect(screen.getByRole("button", { name: "dashboard" })).toBeInTheDocument();
});

test("ダッシュボードから設定の画面を開ける", async () => {
  restoredUser(taro);
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "dashboard" }));

  expect(screen.getByText("settings")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "dashboard" }),
  ).not.toBeInTheDocument();
});
