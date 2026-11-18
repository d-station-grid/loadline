/**
 * 言語の保存（PUT /settings/language）を、アプリ全体で 1 本にまとめる。
 *
 * 選ぶたびにすぐ送ると、先に送った分が遅れてサーバーに届いたとき、保存されるのが先の言語に
 * なる。そこで保存は一度に 1 本だけにして、保存中に選び直したら、選んだ言語を覚えるだけに
 * する。保存が終わった時点で最後の選択が送った言語と違えば、その言語だけをもう一度送る。
 *
 * 画面を切り替えるのは、最後の選択を保存できたときだけ。最後の選択はアプリ全体で 1 つなので、
 * 閉じた画面で送った分の返事が、開き直した画面で選んだ言語を上書きすることもない。
 *
 * ログインの状態が変わったら（ログアウト、入り直し、別の人のログイン）、resetLanguageSave で
 * 区切る。前の区切りの処理は、まだ送っていなければ送らず、送ったあとなら返事が届いても画面と
 * 状態に触れない。
 *
 * 実際に送るリクエストは、区切りをまたいでも一度に 1 本だけにする。同じ人が入り直したとき、
 * 前の区切りで送った分と並ぶと、後からサーバーに届いたほうが残るため。
 */
import type { Language } from "../api";
import { putLanguage } from "./api";

type Request = {
  getIdToken: () => Promise<string>;
  /** 保存できた言語で画面全体を切り替える */
  apply: (language: Language) => void;
};

// ログインの区切りの番号。ログインの状態が変わるたびに進める
let generation = 0;
// 最後に選んだ言語。保存が終わるまでのあいだだけ値がある
let wanted: Language | null = null;
// 最後に選んだ画面から受け取った、トークンの取り方と切り替え方
let request: Request | null = null;
// 最後に送ったリクエスト。次を送る前に、これが終わるのを待つ。失敗しても待つだけなので落とさない
let sending: Promise<unknown> = Promise.resolve();
const choosingListeners = new Set<() => void>();
const failureListeners = new Set<() => void>();

function setWanted(language: Language | null) {
  wanted = language;
  choosingListeners.forEach((listener) => listener());
}

/** 保存中なら、最後に選んだ言語。選択欄はこれを出す */
export function choosingLanguage(): Language | null {
  return wanted;
}

export function subscribeChoosing(listener: () => void): () => void {
  choosingListeners.add(listener);
  return () => choosingListeners.delete(listener);
}

/** 保存できなかったときに呼ぶ。そのとき開いている画面だけが受け取る */
export function subscribeFailure(listener: () => void): () => void {
  failureListeners.add(listener);
  return () => failureListeners.delete(listener);
}

/** ログインの状態が変わったときに呼ぶ。保存中の分の返事は、画面にも状態にも反映しない */
export function resetLanguageSave(): void {
  generation += 1;
  request = null;
  setWanted(null);
}

/** 言語を選ぶ。保存中なら、終わってから最後に選んだ言語だけを送る */
export function chooseLanguage(language: Language, next: Request): void {
  request = next;
  const saving = wanted !== null;
  setWanted(language);
  if (!saving) void run();
}

async function run() {
  // 始めたときの区切り。ログインの状態が変わったら、ここから先は何も触らない
  const mine = generation;
  const current = () => mine === generation;
  // 途中で保存できた言語。最後の選択を保存できなかったら、画面をこれに戻す
  let saved: Language | null = null;
  try {
    for (;;) {
      await sending;
      if (!current()) return;
      const token = await (request as Request).getIdToken();
      // 確かめてから送るまでに待ちを挟まない。ここで区切りが変わっていれば送らない
      if (!current()) return;
      // 待っている間に選び直していれば、最後の選択を送る
      const target = wanted as Language;
      const send = putLanguage(target, token);
      sending = send.catch(() => {});
      const out = await send;
      if (!current()) return;
      saved = out.language ?? target;
      if (wanted === target) {
        (request as Request).apply(saved);
        return;
      }
    }
  } catch {
    if (!current()) return;
    if (saved !== null) (request as Request).apply(saved);
    failureListeners.forEach((listener) => listener());
  } finally {
    if (current()) setWanted(null);
  }
}
