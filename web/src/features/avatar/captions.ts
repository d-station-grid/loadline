/**
 * 字幕を声に合わせる。声には文ごとの時刻がないので、セリフを文に分け、
 * 声の長さを文字数の割合で配って、今読んでいる文を推し量る。
 * 声の速さはほぼ一定なので、文の切れ目の目安としては足りる
 */

/**
 * セリフを文に分ける。「.」「!」「?」のあとに空白が来たところで切る。
 * 「68.8」のような数字の小数点では切らない。分けた文をつなぐと元のセリフに戻る
 * （区切りの空白は前の文の末尾に残す）
 */
export function splitSentences(script: string): string[] {
  return script.split(/(?<=[.!?]["”’)]?\s+)(?=\S)/u).filter((s) => s !== "");
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
