import { fireEvent, render, screen } from "@testing-library/react";
import type { User } from "firebase/auth";
import { beforeEach, expect, test, vi } from "vitest";

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
