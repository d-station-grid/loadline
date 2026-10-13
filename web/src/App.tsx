import {
  onAuthStateChanged,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";
import { useEffect, useState } from "react";

import { login } from "./lib/api";
import { auth, googleProvider } from "./lib/firebase";

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Sign-in failed";
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Firebase がログイン状態を通知するたびに呼ばれる。初回ログインも再読み込みの復元も同じ経路
    return onAuthStateChanged(auth, async (next) => {
      if (next === null) {
        setUser(null);
        setLoading(false);
        return;
      }
      try {
        // api に行があることを確かめてから、ログイン済みにする
        await login(await next.getIdToken());
        setUser(next);
      } catch (e) {
        setError(errorMessage(e));
        await signOut(auth); // null の通知が来て、未ログインの画面に戻る
      } finally {
        setLoading(false);
      }
    });
  }, []);

  async function handleSignIn() {
    setError(null);
    try {
      await signInWithPopup(auth, googleProvider);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (loading) {
    return <p>Loading…</p>;
  }

  if (!user) {
    return (
      <main>
        <h1>loadline</h1>
        <button type="button" onClick={handleSignIn}>
          Sign in with Google
        </button>
        {error && <p role="alert">{error}</p>}
      </main>
    );
  }

  return (
    <main>
      <h1>loadline</h1>
      <p>Signed in as {user.displayName ?? user.email}</p>
      <p>{user.email}</p>
      <button type="button" onClick={() => signOut(auth)}>
        Sign out
      </button>
    </main>
  );
}

export default App;
