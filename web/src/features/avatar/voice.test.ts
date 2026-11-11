import { afterEach, expect, test, vi } from "vitest";

import { rmsLevel, VoiceMeter } from "./voice";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("無音（128 が並ぶ）は 0、振れ幅が大きいほど開き、1 で止まる", () => {
  expect(rmsLevel(new Uint8Array(1024).fill(128))).toBe(0);
  const small = rmsLevel(
    Uint8Array.from({ length: 1024 }, (_, i) => (i % 2 ? 133 : 123)),
  );
  const large = rmsLevel(
    Uint8Array.from({ length: 1024 }, (_, i) => (i % 2 ? 148 : 108)),
  );
  expect(small).toBeGreaterThan(0);
  expect(large).toBeGreaterThan(small);
  expect(
    rmsLevel(Uint8Array.from({ length: 1024 }, (_, i) => (i % 2 ? 255 : 0))),
  ).toBe(1);
  expect(rmsLevel(new Uint8Array(0))).toBe(0);
});

/** Web Audio の代わり。つないだ回数と、resume・close を数える */
function fakeAudioContext(wave: number) {
  const calls = { contexts: 0, sources: 0, resume: 0, close: 0 };
  class FakeAudioContext {
    destination = {};
    constructor() {
      calls.contexts += 1;
    }
    createAnalyser() {
      return {
        fftSize: 0,
        connect() {},
        getByteTimeDomainData(samples: Uint8Array) {
          samples.forEach(
            (_, i) => (samples[i] = i % 2 ? 128 + wave : 128 - wave),
          );
        },
      };
    }
    createMediaElementSource() {
      calls.sources += 1;
      return { connect() {} };
    }
    resume() {
      calls.resume += 1;
      return Promise.resolve();
    }
    close() {
      calls.close += 1;
      return Promise.resolve();
    }
  }
  vi.stubGlobal("AudioContext", FakeAudioContext);
  return calls;
}

test("最初の start で Web Audio につなぎ、同じ <audio> は 2 回つながない", () => {
  const calls = fakeAudioContext(20);
  const meter = new VoiceMeter();
  const audio = document.createElement("audio");

  expect(meter.level()).toBe(0);
  meter.start(audio);
  meter.start(audio);

  expect(calls.contexts).toBe(1);
  expect(calls.sources).toBe(1);
  // 押すたびに resume する（止まっていると鳴らないため）
  expect(calls.resume).toBe(2);
  expect(meter.level()).toBeGreaterThan(0);
});

test("別の <audio>（URL が替わって作り直したもの）はつなぐ", () => {
  const calls = fakeAudioContext(20);
  const meter = new VoiceMeter();

  meter.start(document.createElement("audio"));
  meter.start(document.createElement("audio"));

  expect(calls.contexts).toBe(1);
  expect(calls.sources).toBe(2);
});

test("Web Audio が使えなければ、つながずに大きさ 0 を返す", () => {
  vi.stubGlobal(
    "AudioContext",
    class {
      constructor() {
        throw new Error("not supported");
      }
    },
  );
  const meter = new VoiceMeter();

  expect(() => meter.start(document.createElement("audio"))).not.toThrow();
  expect(meter.level()).toBe(0);
});

test("close で AudioContext を閉じ、大きさは 0 に戻る", () => {
  const calls = fakeAudioContext(20);
  const meter = new VoiceMeter();
  meter.start(document.createElement("audio"));

  meter.close();

  expect(calls.close).toBe(1);
  expect(meter.level()).toBe(0);
});
