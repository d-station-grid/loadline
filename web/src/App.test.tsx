import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/** Firebase が復元するログイン状態を決める。null なら未ログイン。 */
function restoredUser(user: User | null) {
  firebaseAuth.onAuthStateChanged.mockImplementation(
    (_auth: unknown, next: (user: User | null) => void) => {
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
});

test("未ログインならログインのボタンが出る", () => {
  restoredUser(null);
  render(<App />);
  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeInTheDocument();
});

test("ログイン済みなら名前とメールが出る", () => {
  restoredUser(taro);
  render(<App />);
  expect(screen.getByText("Signed in as Taro")).toBeInTheDocument();
  expect(screen.getByText("taro@example.com")).toBeInTheDocument();
});

test("ボタンを押すと Google でログインして api に登録する", async () => {
  restoredUser(null);
  firebaseAuth.signInWithPopup.mockResolvedValue({ user: taro });
  vi.mocked(login).mockResolvedValue({ id: 1, email: "taro@example.com" });
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: "Sign in with Google" }));

  await waitFor(() => expect(login).toHaveBeenCalledWith("token"));
  expect(firebaseAuth.signOut).not.toHaveBeenCalled();
});

test("api で失敗したらログアウトしてエラーを出す", async () => {
  restoredUser(null);
  firebaseAuth.signInWithPopup.mockResolvedValue({ user: taro });
  vi.mocked(login).mockRejectedValue(new Error("API returned 500"));
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: "Sign in with Google" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API returned 500",
  );
  expect(firebaseAuth.signOut).toHaveBeenCalled();
});
