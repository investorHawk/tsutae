// 録音の処理（ブラウザとテストの両方で動く純粋な関数）。録った声の前後の無音を切り、
// 話した長さを測り、音量をそろえ、問題がないかを判定して WAV にする。

const FRAME_SECONDS = 0.02;
const WINDOW_FRAMES = 5; // 100ms のうち 4 枠以上で音があれば声とみなす（クリック音を除く）
const WINDOW_VOICED = 4;
const FLOOR_DB = -100;
const HEAD_PAD_SECONDS = 0.15;
const TAIL_PAD_SECONDS = 0.25;
const FADE_SECONDS = 0.01;
const STOP_CLICK_SECONDS = 0.1; // 停止を押す音を録らないよう、末尾を捨てる
const TARGET_DB = -20;
const MAX_GAIN_DB = 20;
const PEAK_LIMIT_DB = -1;
const CLIP_LEVEL = 0.999;
const CLIP_COUNT = 3;
const TOO_QUIET_DB = -40;
const MIN_SNR_DB = 20;
const HEAD_CUT_SECONDS = 0.05;

const toDb = (linear) =>
  20 * Math.log10(Math.max(linear, 10 ** (FLOOR_DB / 20)));
const toLinear = (db) => 10 ** (db / 20);

const rms = (samples, from, to) => {
  let sum = 0;
  for (let i = from; i < to; i += 1) sum += samples[i] * samples[i];
  return to > from ? Math.sqrt(sum / (to - from)) : 0;
};

const frameDbs = (samples, rate) => {
  const size = Math.round(FRAME_SECONDS * rate);
  const count = Math.floor(samples.length / size);
  return Array.from({ length: count }, (_, i) =>
    toDb(rms(samples, i * size, (i + 1) * size)),
  );
};

const median = (values) => {
  if (values.length === 0) return FLOOR_DB;
  return [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
};

const thresholdDb = (noiseDb) => Math.max(-50, noiseDb + 10);

/** 無音の測定（カウントダウンの間）の中央値。ボタンを押す音に引っ張られない */
export const noiseFloorDb = (samples, rate) => median(frameDbs(samples, rate));

/** 話している範囲（サンプルの位置）。声が無ければ null */
export const speechRange = (samples, rate, noiseDb) => {
  const size = Math.round(FRAME_SECONDS * rate);
  const voiced = frameDbs(samples, rate).map((db) => db > thresholdDb(noiseDb));
  const isSpeechAt = (i) =>
    voiced.slice(i, i + WINDOW_FRAMES).filter(Boolean).length >= WINDOW_VOICED;
  const starts = voiced.map((_, i) => i).filter(isSpeechAt);
  if (starts.length === 0) return null;
  const first = starts[0];
  const last = starts[starts.length - 1] + WINDOW_FRAMES;
  const start = first + voiced.slice(first).indexOf(true);
  const end = last - [...voiced.slice(0, last)].reverse().indexOf(true);
  return { start: start * size, end: Math.min(end * size, samples.length) };
};

/** 声の音量を -20 dBFS にそろえる。上げすぎず、ピークは -1 dBFS まで */
export const normalize = (samples, activeDb) => {
  let peak = 0;
  for (const s of samples) peak = Math.max(peak, Math.abs(s));
  const wanted = toLinear(Math.min(TARGET_DB - activeDb, MAX_GAIN_DB));
  const limit = peak > 0 ? toLinear(PEAK_LIMIT_DB) / peak : wanted;
  const gain = Math.min(wanted, limit);
  return samples.map((s) => s * gain);
};

const withFades = (samples, rate) => {
  const n = Math.min(Math.round(FADE_SECONDS * rate), samples.length);
  return samples.map((s, i) => {
    const left = samples.length - 1 - i;
    if (i < n) return (s * i) / n;
    if (left < n) return (s * left) / n;
    return s;
  });
};

const countClipped = (samples) => {
  let count = 0;
  for (const s of samples) if (Math.abs(s) >= CLIP_LEVEL) count += 1;
  return count;
};

const activeLevelDb = (samples, rate, range, noiseDb) => {
  const voiced = frameDbs(
    samples.subarray(range.start, range.end),
    rate,
  ).filter((db) => db > thresholdDb(noiseDb));
  const power = voiced.reduce((sum, db) => sum + toLinear(db) ** 2, 0);
  return voiced.length > 0 ? toDb(Math.sqrt(power / voiced.length)) : FLOOR_DB;
};

const lengthCheck = (seconds, budget) => {
  const text = `${seconds.toFixed(1)} 秒（目標 ${budget.toFixed(1)} 秒以内）`;
  if (seconds > budget) {
    const over = (seconds - budget).toFixed(1);
    return ["warn", `${text}。${over} 秒長く、次の場面の声に重なる`];
  }
  if (seconds < budget / 2)
    return ["warn", `${text}。途中で止まっていないか確認`];
  return ["ok", text];
};

/** 自動チェックの結果。level は ok / warn（注意）/ ng（問題あり） */
export const checkTake = (metrics, budget) => {
  if (!metrics.hasSpeech) {
    return [{ id: "speech", level: "ng", label: "声が録れていない" }];
  }
  const { clipped, activeDb, noiseDb, startedAt, seconds } = metrics;
  const [lengthLevel, lengthLabel] = lengthCheck(seconds, budget);
  const pick = (id, bad, badLevel, badLabel, okLabel) => ({
    id,
    level: bad ? badLevel : "ok",
    label: bad ? badLabel : okLabel,
  });
  return [
    { id: "speech", level: "ok", label: "声が録れている" },
    { id: "length", level: lengthLevel, label: lengthLabel },
    pick(
      "clip",
      clipped >= CLIP_COUNT,
      "ng",
      "音割れあり。マイクから少し離れる",
      "音割れなし",
    ),
    pick(
      "level",
      activeDb < TOO_QUIET_DB,
      "ng",
      "声が小さすぎる。マイクに近づく",
      "声の大きさは十分",
    ),
    pick(
      "noise",
      activeDb - noiseDb < MIN_SNR_DB,
      "warn",
      "周りの音が大きい",
      "周りの音は静か",
    ),
    pick(
      "head",
      startedAt < HEAD_CUT_SECONDS,
      "warn",
      "話し始めが早く、語頭が切れたかもしれない",
      "語頭は切れていない",
    ),
  ];
};

/** 16bit モノラルの WAV */
export const encodeWav = (samples, rate) => {
  const bytes = new Uint8Array(44 + samples.length * 2);
  const view = new DataView(bytes.buffer);
  const text = (at, s) =>
    [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => {
    const clamped = Math.max(-1, Math.min(1, s));
    view.setInt16(
      44 + i * 2,
      clamped < 0 ? clamped * 32768 : clamped * 32767,
      true,
    );
  });
  return bytes;
};

/** 録った音（raw）と無音の測定（quiet）から、保存する音と判定を作る */
export const processTake = (raw, quiet, rate, budget) => {
  const body = raw.subarray(
    0,
    Math.max(0, raw.length - STOP_CLICK_SECONDS * rate),
  );
  const noiseDb = noiseFloorDb(quiet, rate);
  const range = speechRange(body, rate, noiseDb);
  if (!range) {
    const metrics = { hasSpeech: false, seconds: 0, noiseDb };
    const samples = body.slice();
    return {
      samples,
      metrics,
      checks: checkTake(metrics, budget),
      wav: encodeWav(samples, rate),
    };
  }
  const activeDb = activeLevelDb(body, rate, range, noiseDb);
  const from = Math.max(0, range.start - HEAD_PAD_SECONDS * rate);
  const to = Math.min(body.length, range.end + TAIL_PAD_SECONDS * rate);
  const kept = body.subarray(Math.floor(from), Math.floor(to));
  const samples = normalize(withFades(kept, rate), activeDb);
  const metrics = {
    hasSpeech: true,
    seconds: (range.end - range.start) / rate,
    startedAt: range.start / rate,
    clipped: countClipped(kept),
    activeDb,
    noiseDb,
  };
  return {
    samples,
    metrics,
    checks: checkTake(metrics, budget),
    wav: encodeWav(samples, rate),
  };
};
