import { expect, test } from "vitest";

import { currentSentence, splitSentences } from "./captions";

test("文の終わりの記号と空白で分け、つなぐと元に戻る", () => {
  const script =
    "Last week you chose to keep it easy. Fatigue fell! Ready?  Let's go.";
  const sentences = splitSentences(script);

  expect(sentences).toEqual([
    "Last week you chose to keep it easy. ",
    "Fatigue fell! ",
    "Ready?  ",
    "Let's go.",
  ]);
  expect(sentences.join("")).toBe(script);
});

test("数字の小数点や、引用符の内側では切らない", () => {
  expect(splitSentences('Fatigue was 68.8. He said "rest." Then ok.')).toEqual([
    "Fatigue was 68.8. ",
    'He said "rest." ',
    "Then ok.",
  ]);
});

test("日本語は「。」「！」「？」で分け、つなぐと元に戻る", () => {
  // 日本語の定型のように、文の間に空白がない
  const script =
    "今週は安定した週でした。体力と疲労のバランスもとれています！このまま続けましょう。";
  const sentences = splitSentences(script);

  expect(sentences).toEqual([
    "今週は安定した週でした。",
    "体力と疲労のバランスもとれています！",
    "このまま続けましょう。",
  ]);
  expect(sentences.join("")).toBe(script);
});

test("日本語でも「。」のあとの空白は前の文に残す", () => {
  // Gemini の文は「。」のあとに空白が入ることがある
  const script = "よく頑張りましたね。 今週は軽めにしましょう。";
  const sentences = splitSentences(script);

  expect(sentences).toEqual([
    "よく頑張りましたね。 ",
    "今週は軽めにしましょう。",
  ]);
  expect(sentences.join("")).toBe(script);
});

test("日本語の記号や閉じかっこが続くときは、途中で切らない", () => {
  expect(splitSentences("本当？！すごいですね。")).toEqual([
    "本当？！",
    "すごいですね。",
  ]);
  // かっこの中の「。」のあとも、文は続く
  expect(splitSentences("「休もう。」と言いました。次へ。")).toEqual([
    "「休もう。」と言いました。",
    "次へ。",
  ]);
});

test("区切りがなければ、全体で 1 つの文", () => {
  expect(splitSentences("Keep going")).toEqual(["Keep going"]);
  expect(splitSentences("")).toEqual([]);
});

test("声の長さを文字数の割合で配り、今の文を返す", () => {
  // 10 文字、30 文字。10 秒の声なら、最初の文は 0〜2.5 秒
  const sentences = ["a".repeat(10) + " ", "b".repeat(30)];

  expect(currentSentence(sentences, 1, 10)).toBe(0);
  expect(currentSentence(sentences, 2.4, 10)).toBe(0);
  expect(currentSentence(sentences, 2.6, 10)).toBe(1);
  expect(currentSentence(sentences, 9.9, 10)).toBe(1);
});

test("鳴らす前、鳴らし終えたあと、長さが分からないときは、どの文も選ばない", () => {
  const sentences = ["One. ", "Two."];

  expect(currentSentence(sentences, 0, 10)).toBe(-1);
  expect(currentSentence(sentences, 10, 10)).toBe(-1);
  expect(currentSentence(sentences, 1, Number.NaN)).toBe(-1);
  expect(currentSentence(sentences, 1, Number.POSITIVE_INFINITY)).toBe(-1);
  expect(currentSentence([], 1, 10)).toBe(-1);
});
