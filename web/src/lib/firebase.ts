import { initializeApp } from "firebase/app";
import {
  connectAuthEmulator,
  getAuth,
  GoogleAuthProvider,
} from "firebase/auth";

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

// 通しのテスト（e2e/）では、本物の Firebase ではなく手元の Auth エミュレータにつなぐ。
// 本番のビルドには設定しないので、この分岐は通らない
const emulatorUrl = import.meta.env.VITE_FIREBASE_AUTH_EMULATOR_URL;
if (emulatorUrl) {
  connectAuthEmulator(auth, emulatorUrl, { disableWarnings: true });
}
export const googleProvider = new GoogleAuthProvider();
