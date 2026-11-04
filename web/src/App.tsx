import {
  onAuthStateChanged,
  signInAnonymously,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";
import { useEffect, useRef, useState } from "react";

import { ApiError, login } from "./lib/api";
import { auth, googleProvider } from "./lib/firebase";
import DashboardPage from "./pages/DashboardPage";
import SettingsPage from "./pages/SettingsPage";
import WorkoutPage from "./pages/WorkoutPage";
import WorkoutsPage from "./pages/WorkoutsPage";

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Sign-in failed";
}

/** ログインで api に断られたときの文言。ゲストはデモデータを見るので、
 * まだ入れていない環境では 503 になる。Google のログインの 503 はほかの失敗と同じに扱う */
function loginErrorMessage(e: unknown, guest: boolean): string {
  if (guest && e instanceof ApiError && e.status === 503) {
    return "Guest mode isn't available right now.";
  }
  return errorMessage(e);
}

// ログイン済みの画面。ルーティングのライブラリは入れず、state で切り替える
type View =
  | { name: "dashboard" }
  | { name: "workouts" }
  | { name: "workout"; id: number }
  | { name: "settings" };

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<View>({ name: "dashboard" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // アカウントを消したあとのログアウト。終わるまでどのページも描かず、api を呼ばせない
  const [signingOut, setSigningOut] = useState<"pending" | "failed" | null>(
    null,
  );
  // Firebase の通知の連番。api の応答を待つ間に次の通知が来たら、古い処理は状態を触らない
  const latest = useRef(0);

  useEffect(() => {
    // Firebase がログイン状態を通知するたびに呼ばれる。初回ログインも再読み込みの復元も同じ経路
    const unsubscribe = onAuthStateChanged(auth, async (next) => {
      const seq = ++latest.current;
      const isLatest = () => seq === latest.current;

      if (next === null) {
        setUser(null);
        setSigningOut(null);
        setLoading(false);
        return;
      }
      try {
        // api に行があることを確かめてから、ログイン済みにする
        await login(await next.getIdToken());
        if (isLatest()) {
          setUser(next);
        }
      } catch (e) {
        if (isLatest()) {
          setError(loginErrorMessage(e, next.isAnonymous));
          await signOut(auth); // null の通知が来て、未ログインの画面に戻る
        }
      } finally {
        if (isLatest()) {
          setLoading(false);
        }
      }
    });
    return () => {
      latest.current += 1;
      unsubscribe();
    };
  }, []);

  async function handleSignIn() {
    setError(null);
    try {
      await signInWithPopup(auth, googleProvider);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  /** ゲストは Firebase の匿名ログイン。api はデモの利用者として扱い、見るだけにする */
  async function handleGuest() {
    setError(null);
    try {
      await signInAnonymously(auth);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function signOutAfterDelete() {
    setSigningOut("pending");
    try {
      await signOut(auth);
    } catch {
      setSigningOut("failed");
      return;
    }
    // ふつうは null の通知で戻る。通知を待たずにここでも戻す
    setUser(null);
    setSigningOut(null);
  }

  function handleDeleted() {
    // 古い ID トークンはまだ期限内なので、隠した一覧も含めてページを外してから抜ける
    latest.current += 1;
    setView({ name: "dashboard" });
    void signOutAfterDelete();
  }

  if (loading) {
    return <p>Loading…</p>;
  }

  if (signingOut) {
    return (
      <main>
        <h1>loadline</h1>
        {signingOut === "pending" ? (
          <p>Signing out…</p>
        ) : (
          <>
            <p role="alert">Couldn't sign out. Please try again.</p>
            <button type="button" onClick={signOutAfterDelete}>
              Sign out
            </button>
          </>
        )}
      </main>
    );
  }

  if (!user) {
    return (
      <main>
        <h1>loadline</h1>
        <button type="button" onClick={handleSignIn}>
          Sign in with Google
        </button>{" "}
        <button type="button" onClick={handleGuest}>
          Try as a guest
        </button>
        <p>Guests can look around demo data without signing up.</p>
        {error && <p role="alert">{error}</p>}
      </main>
    );
  }

  return (
    <main>
      <header>
        <h1>loadline</h1>
        <nav aria-label="Main">
          <button type="button" onClick={() => setView({ name: "dashboard" })}>
            Dashboard
          </button>
          <button type="button" onClick={() => setView({ name: "workouts" })}>
            Workouts
          </button>
          <button type="button" onClick={() => setView({ name: "settings" })}>
            Settings
          </button>
        </nav>
        <p>
          {user.isAnonymous ? (
            "Viewing demo data as a guest (read-only)"
          ) : (
            <>
              Signed in as {user.displayName ?? user.email}{" "}
              <span>{user.email}</span>
            </>
          )}{" "}
          <button type="button" onClick={() => signOut(auth)}>
            Sign out
          </button>
        </p>
      </header>
      {/* ダッシュボードは隠さずに外す。隠した要素の中では ECharts が幅 0 で描いてしまうため */}
      {view.name === "dashboard" && (
        <DashboardPage
          user={user}
          onOpenSettings={() => setView({ name: "settings" })}
        />
      )}
      {/* 一覧はマウントしたまま隠す。詳細から戻ったときに期間と Load more の続きを残すため */}
      <div hidden={view.name !== "workouts"}>
        <WorkoutsPage
          user={user}
          onSelect={(id) => setView({ name: "workout", id })}
        />
      </div>
      {view.name === "workout" && (
        <WorkoutPage
          user={user}
          workoutId={view.id}
          onBack={() => setView({ name: "workouts" })}
        />
      )}
      {view.name === "settings" && (
        <SettingsPage user={user} onDeleted={handleDeleted} />
      )}
    </main>
  );
}

export default App;
