import { act, fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

import type { UserOut } from "./api";
import App from "./App";
import { ApiError, login } from "./lib/api";

const firebaseAuth = vi.hoisted(() => ({
  onAuthStateChanged: vi.fn(),
  signInAnonymously: vi.fn(),
  signInWithPopup: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("firebase/auth", () => firebaseAuth);
vi.mock("./lib/firebase", () => ({ auth: {}, googleProvider: {} }));
vi.mock("./lib/api", async (importOriginal) => ({
  // ApiError は本物を使う。状態コードで文言を出し分けるため
  ApiError: (await importOriginal<typeof import("./lib/api")>()).ApiError,
  login: vi.fn(),
}));
// 設定ページは自分のテストで見る。ここではログインの流れだけ
vi.mock("./pages/SettingsPage", () => ({
  default: ({ onDeleted }: { onDeleted: () => void }) => (
    <button type="button" onClick={onDeleted}>
      settings
    </button>
  ),
}));
const workoutsPage = vi.hoisted(() => vi.fn());
vi.mock("./pages/WorkoutsPage", () => ({
  default: () => {
    workoutsPage();
    return <p>workouts</p>;
  },
}));
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
  // ログアウトが済むと、Firebase は null の通知を出す
  firebaseAuth.signOut.mockImplementation(async () => {
    notify(null);
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

  expect(screen.getByRole("button", { name: "settings" })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "dashboard" }),
  ).not.toBeInTheDocument();
});

test("アカウントを消せたら、ほかの画面を描かずにログアウトし、ログイン前の画面に戻る", async () => {
  restoredUser(taro);
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  workoutsPage.mockClear();

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "settings" }));
  });

  expect(firebaseAuth.signOut).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Signed in as Taro")).not.toBeInTheDocument();
  // 消したあとに api を呼ぶ画面を描き直さない
  expect(workoutsPage).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "dashboard" }),
  ).not.toBeInTheDocument();
  expect(login).toHaveBeenCalledTimes(1);
});

test("消したあとにもう一度ログインすると、ダッシュボードから始まる", async () => {
  restoredUser(taro);
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "settings" }));
  });

  fireEvent.click(screen.getByRole("button", { name: "Sign in with Google" }));

  expect(
    await screen.findByRole("button", { name: "dashboard" }),
  ).toBeInTheDocument();
});

test("ログアウトが終わるまでは、ログイン画面もページも出さない", async () => {
  restoredUser(taro);
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  let finishSignOut: () => void = () => {};
  firebaseAuth.signOut.mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finishSignOut = () => {
          notify(null);
          resolve();
        };
      }),
  );
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  workoutsPage.mockClear();

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "settings" }));
  });

  expect(screen.getByText("Signing out…")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Sign in with Google" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Signed in as Taro")).not.toBeInTheDocument();
  expect(workoutsPage).not.toHaveBeenCalled();

  await act(async () => {
    finishSignOut();
  });

  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeInTheDocument();
  expect(workoutsPage).not.toHaveBeenCalled();
});

test("消したあとのログアウトに失敗したら、やり直せる", async () => {
  restoredUser(taro);
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  firebaseAuth.signOut.mockRejectedValueOnce(new Error("network"));
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  workoutsPage.mockClear();

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "settings" }));
  });

  expect(screen.getByRole("alert")).toHaveTextContent(
    "Couldn't sign out. Please try again.",
  );
  expect(screen.queryByText("Signed in as Taro")).not.toBeInTheDocument();
  expect(workoutsPage).not.toHaveBeenCalled();

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  });

  expect(firebaseAuth.signOut).toHaveBeenCalledTimes(2);
  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeInTheDocument();
});

const guest = {
  displayName: null,
  email: null,
  isAnonymous: true,
  getIdToken: async () => "guest-token",
} as unknown as User;

test("ゲストで試すと匿名でログインし、見るだけの案内が出る", async () => {
  restoredUser(null);
  firebaseAuth.signInAnonymously.mockImplementation(async () => {
    notify(guest);
    return { user: guest };
  });
  vi.mocked(login).mockResolvedValue({ id: 9, email: "demo@loadline.invalid" });
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: "Try as a guest" }));

  expect(
    await screen.findByText(/Viewing demo data as a guest/),
  ).toBeInTheDocument();
  expect(firebaseAuth.signInAnonymously).toHaveBeenCalled();
  expect(login).toHaveBeenCalledWith("guest-token");
});

test("デモデータがない環境では、ゲストに使えないと出してログアウトする", async () => {
  restoredUser(null);
  firebaseAuth.signInAnonymously.mockImplementation(async () => {
    notify(guest);
    return { user: guest };
  });
  vi.mocked(login).mockRejectedValue(new ApiError(503));
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: "Try as a guest" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Guest mode isn't available right now.",
  );
  expect(firebaseAuth.signOut).toHaveBeenCalled();
});

test("Google のログインで api が 503 でも、ゲストの文言にはしない", async () => {
  restoredUser(null);
  vi.mocked(login).mockRejectedValue(new ApiError(503));
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: "Sign in with Google" }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("API returned 503");
  expect(alert).not.toHaveTextContent("Guest mode");
});
