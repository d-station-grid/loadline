/**
 * 字幕を声に合わせる。声には文ごとの時刻がないので、セリフを文に分け、
 * 声の長さを文字数の割合で配って、今読んでいる文を推し量る。
 * 声の速さはほぼ一定なので、文の切れ目の目安としては足りる
 */

/**
 * セリフを文に分ける。英語は「.」「!」「?」のあとに空白が来たところで切る
 * （「68.8」のような数字の小数点では切らない）。日本語は「。」「！」「？」のあとで切る。
 * 日本語は文の間に空白がないことが多いが、あればそれも前の文に含める。「？！」のように
 * 記号が続くときと、閉じかっこ（」』））が続くときは切らない。「「休もう。」と言った。」の
 * ように、かっこの中の「。」のあとも文は続くため。
 * 分けた文をつなぐと元のセリフに戻る（区切りの空白は前の文の末尾に残す）
 */
const SENTENCE_BREAK = new RegExp(
  [
    // 英語: 文末の記号（と閉じる引用符）のあと、空白を挟んで次の文
    String.raw`(?<=[.!?]["”’)]?\s+)(?=\S)`,
    // 日本語: 文末の記号（と空白）のあと。次が記号や閉じかっこなら切らない
    String.raw`(?<=[。！？]\s*)(?=[^\s。！？!?」』）)])`,
  ].join("|"),
  "u",
);

export function splitSentences(script: string): string[] {
  return script.split(SENTENCE_BREAK).filter((s) => s !== "");
}

/**
 * 今読んでいる文の番号。時刻は秒。声の長さが分からないとき、鳴らす前（0 秒）、
 * 鳴らし終えたあとは -1（どの文も目立たせない）
 */
export function currentSentence(
  sentences: string[],
  time: number,
  duration: number,
): number {
  if (!Number.isFinite(duration) || duration <= 0) return -1;
  if (time <= 0 || time >= duration) return -1;
  const lengths = sentences.map((s) => s.trim().length);
  const total = lengths.reduce((a, b) => a + b, 0);
  if (total === 0) return -1;
  let end = 0;
  for (let i = 0; i < lengths.length; i++) {
    end += lengths[i];
    if (time < (end / total) * duration) return i;
  }
  return lengths.length - 1;
}
