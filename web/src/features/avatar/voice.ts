/**
 * 再生中の声の大きさを読み取る。<audio> を Web Audio につなぎ、波形の RMS を 0〜1 で返す。
 * アバターの口を動かすのに使う。
 *
 * - AudioContext は利用者の操作のあとでしか鳴らせないので、再生ボタンを押したときに
 *   start() で作り、resume する
 * - 1 つの <audio> は 1 回しか Web Audio につなげないので、つないだ要素を覚えておく。
 *   つないだあとの声は AudioContext を通って鳴る
 * - 音声は CORS つきで読む（crossOrigin="anonymous"）。CORS がない音声をつなぐと、
 *   ブラウザは無音を流す
 * - Web Audio が使えないブラウザでは、つながずにそのまま鳴らし、大きさは 0 を返す
 *   （口は動かないが、声は聞ける）
 */
export class VoiceMeter {
  private context: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private connected = new WeakSet<HTMLMediaElement>();
  private samples = new Uint8Array(1024);

  /** 再生ボタンを押したときに呼ぶ。押した操作の中で呼ばないと、Safari は鳴らさない */
  start(audio: HTMLMediaElement): void {
    try {
      if (!this.context) {
        this.context = new AudioContext();
        this.analyser = this.context.createAnalyser();
        this.analyser.fftSize = this.samples.length;
        this.analyser.connect(this.context.destination);
      }
      if (!this.connected.has(audio) && this.analyser) {
        this.context.createMediaElementSource(audio).connect(this.analyser);
        this.connected.add(audio);
      }
      void this.context.resume().catch(() => {});
    } catch {
      // Web Audio が使えなければ、つながずにそのまま鳴らす
    }
  }

  /** 今の声の大きさ（0〜1）。鳴っていなければ 0 に近い */
  level(): number {
    const analyser = this.analyser;
    if (!analyser) return 0;
    analyser.getByteTimeDomainData(this.samples);
    return rmsLevel(this.samples);
  }

  /**
   * 画面を離れるときに呼ぶ。つないだ <audio> は別の AudioContext につなぎ直せないので、
   * その <audio> も一緒に外れるときだけ呼ぶ
   */
  close(): void {
    void this.context?.close().catch(() => {});
    this.context = null;
    this.analyser = null;
    this.connected = new WeakSet();
  }
}

/** 声の RMS をこの倍率で口の開きにする。Kokoro の声で、大きい母音で口がほぼ開ききる */
const LEVEL_GAIN = 6;

/**
 * 8 ビットの波形（128 が無音）から、口の開き（0〜1）を出す
 */
export function rmsLevel(samples: Uint8Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (const s of samples) {
    const v = (s - 128) / 128;
    sum += v * v;
  }
  return Math.min(1, Math.sqrt(sum / samples.length) * LEVEL_GAIN);
}
