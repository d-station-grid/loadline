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
import Landing from "./components/Landing";
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
    return <p className="app-loading">Loading…</p>;
  }

  if (signingOut) {
    return (
      <main className="app-main">
        <h1 className="logo">
          load<span>line</span>
        </h1>
        {signingOut === "pending" ? (
          <p>Logging out…</p>
        ) : (
          <>
            <p role="alert">Couldn't log out. Please try again.</p>
            <button type="button" onClick={signOutAfterDelete}>
              Log out
            </button>
          </>
        )}
      </main>
    );
  }

  if (!user) {
    return (
      <Landing onSignIn={handleSignIn} onGuest={handleGuest} error={error} />
    );
  }

  // ヘッダーで下線を引く項目。詳細は一覧の中の画面なので Workouts に引く
  const current = view.name === "workout" ? "workouts" : view.name;
  const navItems: { view: View; label: string }[] = [
    { view: { name: "dashboard" }, label: "Dashboard" },
    { view: { name: "workouts" }, label: "Workouts" },
    { view: { name: "settings" }, label: "Settings" },
  ];

  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <h1 className="logo">
            load<span>line</span>
          </h1>
          <nav aria-label="Main" className="app-nav">
            {navItems.map((item) => (
              <button
                key={item.view.name}
                type="button"
                aria-current={current === item.view.name ? "page" : undefined}
                onClick={() => setView(item.view)}
              >
                {item.label}
              </button>
            ))}
            <button
              type="button"
              className="button-outline"
              onClick={() => signOut(auth)}
            >
              Log out
            </button>
          </nav>
        </div>
      </header>
      {user.isAnonymous && (
        <p className="guest-banner">Viewing demo data as a guest (read-only)</p>
      )}
      <main className="app-main">
        {/* ダッシュボードは隠さずに外す。隠した要素の中では ECharts が幅 0 で描いてしまうため */}
        {view.name === "dashboard" && (
          <DashboardPage
            user={user}
            onOpenSettings={() => setView({ name: "settings" })}
            onOpenWorkouts={() => setView({ name: "workouts" })}
            onOpenWorkout={(id) => setView({ name: "workout", id })}
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
    </>
  );
}

export default App;
