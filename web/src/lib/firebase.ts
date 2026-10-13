import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";

function requireEnv(name: string): string {
  const value = import.meta.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. Copy web/.env.example to web/.env.local.`,
    );
  }
  return value;
}

const app = initializeApp({
  apiKey: requireEnv("VITE_FIREBASE_API_KEY"),
  authDomain: requireEnv("VITE_FIREBASE_AUTH_DOMAIN"),
  projectId: requireEnv("VITE_FIREBASE_PROJECT_ID"),
  appId: requireEnv("VITE_FIREBASE_APP_ID"),
});

export const auth = getAuth(app);
export const googleProvider = new GoogleAuthProvider();
