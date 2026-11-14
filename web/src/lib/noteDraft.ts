/** 直している途中の本文とラベル。メモの id ごとに持ち、別のメモへ移っても残す */
export type EditDraft = { body: string; label: string };
export type EditDrafts = Record<number, EditDraft>;

/**
 * メモの書きかけのすべて。新しく書く本文とラベル、直している途中のメモ（id ごと）。
 * モーダルを閉じて Notes が外れても残るよう、ダッシュボードが持つ。
 */
export type NoteDraft = { body: string; label: string; edits: EditDrafts };

export const EMPTY_NOTE_DRAFT: NoteDraft = { body: "", label: "", edits: {} };
