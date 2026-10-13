import {
  onAuthStateChanged,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";
import { useEffect, useState } from "react";

import { login } from "./lib/api";
import { auth, googleProvider } from "./lib/firebase";

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Firebase がログイン状態を復元したら呼ばれる。戻り値は購読の解除
    return onAuthStateChanged(auth, (next) => {
      setUser(next);
      setLoading(false);
    });
  }, []);

  async function handleSignIn() {
    setError(null);
    try {
      const result = await signInWithPopup(auth, googleProvider);
      await login(await result.user.getIdToken());
    } catch (e) {
      // api で行を作れなければログイン済みにしない
      await signOut(auth);
      setError(e instanceof Error ? e.message : "Sign-in failed");
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
