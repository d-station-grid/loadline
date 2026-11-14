import type { User } from "firebase/auth";
import useSWR, { type SWRConfiguration, useSWRConfig } from "swr";

import type { NoteOut } from "../api";
import { getDashboard, getNotes } from "./api";

/**
 * SWR の共通の設定。App の SWRConfig とテストで同じものを使う。
 *
 * - 画面に戻るたびに裏で読み直すので、タブに戻っただけでは読み直さない
 * - 失敗したら自動では読み直さない。画面の Retry で読み直す
 */
export const SWR_OPTIONS: SWRConfiguration = {
  revalidateOnFocus: false,
  shouldRetryOnError: false,
};

/** 利用者ごとに分けたキー。ログアウトして別の人が入っても、前の人の結果を出さない */
function dashboardKey(user: User, weeks: number) {
  return ["dashboard", user.uid, weeks] as const;
}

function notesKey(user: User, since: string) {
  return ["notes", user.uid, since] as const;
}

/**
 * 直近 weeks 週のダッシュボード。期間ごとに結果を持ち、同じ期間を何か所から頼んでも 1 回だけ読む。
 * 種目は api が by_sport に 3 つまとめて返すので、種目を切り替えても読み直さない。
 * ほかの画面から戻ったときは、持っている結果をすぐ出して裏で読み直す。
 */
export function useDashboard(user: User, weeks: number) {
  return useSWR(dashboardKey(user, weeks), async () =>
    getDashboard({ weeks }, await user.getIdToken()),
  );
}

/** since 以降のメモ。チャートの点線とメモのモーダルが同じ結果を見る */
export function useNotes(user: User, since: string | undefined) {
  return useSWR(
    since === undefined ? null : notesKey(user, since),
    async () => (await getNotes({ since }, await user.getIdToken())).items,
  );
}

/**
 * メモを書き換えたあとの更新。update を渡すと since の一覧を手元で先に直し（読み直しが
 * 届くまでの間も見えるように）、この利用者のメモの一覧を、ほかの期間の分もすべて裏で読み直す。
 * 読み直しは待たない。
 */
export function useUpdateNotes(user: User) {
  const { mutate } = useSWRConfig();
  return async (since: string, update?: (items: NoteOut[]) => NoteOut[]) => {
    if (update) {
      await mutate(
        notesKey(user, since),
        (items: NoteOut[] | undefined) => (items ? update(items) : items),
        { revalidate: false },
      );
    }
    void mutate(
      (key) => Array.isArray(key) && key[0] === "notes" && key[1] === user.uid,
    );
  };
}
