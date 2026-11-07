// 録音アプリ（scripts/voice-recorder）の音声処理と保存。マイクと画面はここでは試さない。
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  checkTake,
  encodeWav,
  normalize,
  processTake,
  speechRange,
} from "../scripts/voice-recorder/audio.mjs";
import {
  consultPrompt,
  countChars,
  diffChars,
  normalizeScript,
} from "../scripts/voice-recorder/script.mjs";
import {
  isVoiceKey,
  keepTake,
  loadScriptEdits,
  parseRange,
  saveScriptEdit,
  saveVoice,
  savedVoice,
  wavSeconds,
} from "../scripts/voice-recorder/store.mjs";

const RATE = 48000;

/** 周波数 220Hz の声の代わり。amp は 0〜1 */
const tone = (seconds, amp) =>
  Float32Array.from({ length: Math.round(seconds * RATE) }, (_, i) =>
    amp === 0 ? 0 : amp * Math.sin((2 * Math.PI * 220 * i) / RATE),
  );

const noise = (seconds, amp) =>
  Float32Array.from(
    { length: Math.round(seconds * RATE) },
    (_, i) => amp * (((i * 7919) % 2000) / 1000 - 1),
  );

const join3 = (...parts) => {
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
};

describe("encodeWav", () => {
  it("16bit モノラルの WAV を書く", () => {
    const bytes = encodeWav(Float32Array.from([0, 1, -1, 2]), RATE);
    const view = new DataView(bytes.buffer);
    expect(new TextDecoder().decode(bytes.slice(0, 4))).toBe("RIFF");
    expect(new TextDecoder().decode(bytes.slice(8, 12))).toBe("WAVE");
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(RATE);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(8);
    expect(view.getInt16(46, true)).toBe(32767);
    expect(view.getInt16(48, true)).toBe(-32768);
    // 1 を超える値は端で止める
    expect(view.getInt16(50, true)).toBe(32767);
  });
});

describe("speechRange", () => {
  it("前後の無音を除いた、話している範囲を返す", () => {
    const s = join3(tone(1, 0), tone(2, 0.2), tone(1, 0));
    const r = speechRange(s, RATE, -90);
    expect(r.start / RATE).toBeCloseTo(1, 1);
    expect(r.end / RATE).toBeCloseTo(3, 1);
  });

  it("短いクリック音は声に数えない", () => {
    const s = join3(tone(0.5, 0), tone(0.03, 0.8), tone(0.5, 0), tone(1, 0.2));
    const r = speechRange(s, RATE, -90);
    expect(r.start / RATE).toBeCloseTo(1.03, 1);
  });

  it("声が無ければ null", () => {
    expect(speechRange(noise(2, 0.0005), RATE, -66)).toBeNull();
  });
});

describe("normalize", () => {
  it("声の音量を -20 dBFS にそろえ、元の配列は書き換えない", () => {
    const s = tone(1, 0.02);
    const copy = s.slice();
    const out = normalize(s, -30);
    expect(s).toEqual(copy);
    expect(Math.max(...out)).toBeCloseTo(0.02 * 10 ** (10 / 20), 2);
  });

  it("上げても頭打ちにならない（ピーク -1 dBFS まで）", () => {
    const out = normalize(tone(1, 0.8), -40);
    expect(Math.max(...out)).toBeLessThanOrEqual(10 ** (-1 / 20) + 1e-6);
  });
});

describe("checkTake", () => {
  const good = {
    hasSpeech: true,
    clipped: 0,
    activeDb: -22,
    noiseDb: -60,
    startedAt: 0.5,
    seconds: 10,
  };
  const levels = (m, budget = 14.7) =>
    Object.fromEntries(checkTake(m, budget).map((c) => [c.id, c.level]));

  it("問題が無ければ全て ok", () => {
    expect(new Set(Object.values(levels(good)))).toEqual(new Set(["ok"]));
  });

  it("声が無ければ ng", () => {
    expect(levels({ ...good, hasSpeech: false }).speech).toBe("ng");
  });

  it("音割れは ng", () => {
    expect(levels({ ...good, clipped: 12 }).clip).toBe("ng");
  });

  it("声が小さすぎれば ng", () => {
    expect(levels({ ...good, activeDb: -45 }).level).toBe("ng");
  });

  it("周りの音が大きければ warn", () => {
    expect(levels({ ...good, noiseDb: -30 }).noise).toBe("warn");
  });

  it("目標の時間を超えれば warn（止めない）", () => {
    expect(levels({ ...good, seconds: 15 }).length).toBe("warn");
  });

  it("目標の半分より短ければ warn", () => {
    expect(levels({ ...good, seconds: 5 }).length).toBe("warn");
  });

  it("話し始めが録音の頭に近ければ warn（語頭が切れた疑い）", () => {
    expect(levels({ ...good, startedAt: 0.02 }).head).toBe("warn");
  });
});

describe("processTake", () => {
  it("前後の無音を切り、話した長さを測って WAV にする", () => {
    const s = join3(tone(1, 0), tone(5, 0.1), tone(1, 0));
    const take = processTake(s, new Float32Array(RATE), RATE, 8);
    expect(take.metrics.seconds).toBeCloseTo(5, 0);
    expect(take.metrics.hasSpeech).toBe(true);
    // 切った前後に 0.15 秒と 0.25 秒の余白が残る
    expect(take.samples.length / RATE).toBeCloseTo(5 + 0.15 + 0.25, 0);
    expect(new TextDecoder().decode(take.wav.slice(0, 4))).toBe("RIFF");
    expect(take.checks.every((c) => c.level === "ok")).toBe(true);
  });

  it("停止を押すときの音を避けて末尾を捨てる", () => {
    const s = join3(tone(1, 0), tone(5, 0.1), tone(0.05, 0), tone(0.05, 0.9));
    const take = processTake(s, new Float32Array(RATE), RATE, 14.7);
    expect(take.metrics.clipped).toBe(0);
    expect(take.metrics.seconds).toBeCloseTo(5, 0);
  });

  it("元の配列を書き換えない", () => {
    const s = join3(tone(1, 0), tone(3, 0.1));
    const copy = s.slice();
    processTake(s, new Float32Array(RATE), RATE, 14.7);
    expect(s).toEqual(copy);
  });

  it("声が無い録音は ng", () => {
    const take = processTake(tone(2, 0), new Float32Array(RATE), RATE, 14.7);
    expect(take.metrics.hasSpeech).toBe(false);
    expect(take.checks.find((c) => c.id === "speech").level).toBe("ng");
  });
});

describe("parseRange（音声の部分取得。Safari などの WebKit はこれが無いと再生しない）", () => {
  it("指定が無ければ null（全体を返す）", () => {
    expect(parseRange(undefined, 100)).toBeNull();
  });

  it("開始と終了の指定", () => {
    expect(parseRange("bytes=0-1", 100)).toEqual({ start: 0, end: 1 });
    expect(parseRange("bytes=10-19", 100)).toEqual({ start: 10, end: 19 });
  });

  it("終了が無ければ最後まで、末尾を超えれば最後で止める", () => {
    expect(parseRange("bytes=90-", 100)).toEqual({ start: 90, end: 99 });
    expect(parseRange("bytes=90-500", 100)).toEqual({ start: 90, end: 99 });
  });

  it("末尾から n バイトの指定", () => {
    expect(parseRange("bytes=-10", 100)).toEqual({ start: 90, end: 99 });
    expect(parseRange("bytes=-500", 100)).toEqual({ start: 0, end: 99 });
  });

  it("満たせない指定は invalid", () => {
    expect(parseRange("bytes=100-", 100)).toBe("invalid");
    expect(parseRange("bytes=20-10", 100)).toBe("invalid");
    expect(parseRange("bytes=-0", 100)).toBe("invalid");
  });

  it("読めない・複数の指定は null（全体を返す）", () => {
    expect(parseRange("items=0-1", 100)).toBeNull();
    expect(parseRange("bytes=0-1,5-6", 100)).toBeNull();
  });
});

describe("保存", () => {
  const wav = encodeWav(tone(2, 0.1), RATE);
  let root;
  let voiceDir;
  let oldDir;

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), "voice-rec-"));
    voiceDir = join(root, "voice");
    oldDir = join(root, "old");
    mkdirSync(voiceDir);
  });

  afterEach(() => rmSync(root, { recursive: true, force: true }));

  it("場面のキーは b01〜b12 だけ", () => {
    expect(isVoiceKey("b01")).toBe(true);
    expect(isVoiceKey("b12")).toBe(true);
    expect(isVoiceKey("b00")).toBe(false);
    expect(isVoiceKey("b13")).toBe(false);
    expect(isVoiceKey("../b01")).toBe(false);
  });

  it("b01.wav の名前で保存し、秒を読める", () => {
    saveVoice(voiceDir, oldDir, "b01", wav, new Date(0));
    expect(readFileSync(join(voiceDir, "b01.wav"))).toEqual(Buffer.from(wav));
    expect(savedVoice(voiceDir, "b01")).toEqual({
      file: "b01.wav",
      seconds: 2,
    });
    expect(savedVoice(voiceDir, "b02")).toBeNull();
    expect(wavSeconds(Buffer.from(wav))).toBe(2);
  });

  it("前の録音は voice の外へ退避し、上書きで失わない", () => {
    writeFileSync(join(voiceDir, "b01_intro.m4a"), "old-m4a");
    writeFileSync(join(voiceDir, "b01.wav"), "old-wav");
    writeFileSync(join(voiceDir, "b02.wav"), "other");
    writeFileSync(join(voiceDir, "README.md"), "readme");
    saveVoice(voiceDir, oldDir, "b01", wav, new Date(0));
    expect(readdirSync(voiceDir).sort()).toEqual([
      "README.md",
      "b01.wav",
      "b02.wav",
    ]);
    expect(readdirSync(oldDir).sort()).toEqual([
      "19700101-000000-b01.wav",
      "19700101-000000-b01_intro.m4a",
    ]);
    expect(readFileSync(join(voiceDir, "b02.wav"), "utf8")).toBe("other");
  });

  it("WAV でないものと不正なキーは保存しない", () => {
    expect(() =>
      saveVoice(voiceDir, oldDir, "b01", Buffer.from("not wav"), new Date(0)),
    ).toThrow();
    expect(() =>
      saveVoice(voiceDir, oldDir, "../evil", wav, new Date(0)),
    ).toThrow();
    expect(readdirSync(voiceDir)).toEqual([]);
  });

  it("全ての録音の控えを残す", () => {
    const takesDir = join(root, "takes");
    const name = keepTake(takesDir, "b03", "rehearsal", wav, new Date(0));
    expect(name).toBe("19700101-000000-b03-rehearsal.wav");
    expect(existsSync(join(takesDir, name))).toBe(true);
    expect(() => keepTake(takesDir, "b03", "../x", wav, new Date(0))).toThrow();
  });
});

describe("原稿の変更（scripts/voice-recorder/script.mjs）", () => {
  const rebuild = (segments, types) =>
    segments
      .filter((s) => types.includes(s.type))
      .map((s) => s.text)
      .join("");

  describe("diffChars", () => {
    it("変えていなければ全て same", () => {
      expect(diffChars("同じ文", "同じ文")).toEqual([
        { type: "same", text: "同じ文" },
      ]);
    });

    it("置き換えを削除と追加で返す", () => {
      expect(diffChars("印刷すると消します", "印刷が済むと消します")).toEqual([
        { type: "same", text: "印刷" },
        { type: "del", text: "する" },
        { type: "add", text: "が済む" },
        { type: "same", text: "と消します" },
      ]);
    });

    it("どんな変更でも、元の文と変更後の文を復元できる", () => {
      const before = "新しいレジメンも、医師が Claude に文で伝えるだけ。";
      const after = "レジメンも、医師がチャットから文で伝えるだけです。追加";
      const d = diffChars(before, after);
      expect(rebuild(d, ["same", "del"])).toBe(before);
      expect(rebuild(d, ["same", "add"])).toBe(after);
    });

    it("空の文との比較", () => {
      expect(diffChars("", "追加")).toEqual([{ type: "add", text: "追加" }]);
      expect(diffChars("削除", "")).toEqual([{ type: "del", text: "削除" }]);
    });
  });

  describe("normalizeScript", () => {
    it("前後の空白と改行を除く（字幕は 1 つの文）", () => {
      expect(normalizeScript("  一文目。\n二文目。\r\n")).toBe(
        "一文目。二文目。",
      );
    });
  });

  describe("countChars", () => {
    it("空白を除いて数える（台本の字数と同じ数え方）", () => {
      expect(countChars("私は 25 年間")).toBe(6);
    });
  });

  describe("consultPrompt", () => {
    const prompt = consultPrompt({
      index: 6,
      title: "受診日",
      budget: 14.7,
      original: "印刷すると消します。",
      edited: "印刷が済むと消します。",
    });

    it("/btw で始まり、1 行にまとまる（貼り付けても折りたたまれにくい）", () => {
      expect(prompt.startsWith("/btw ")).toBe(true);
      expect(prompt).not.toContain("\n");
    });

    it("場面・目標の時間・元の文・変更後の文・字数を含む", () => {
      expect(prompt).toContain("場面 6「受診日」");
      expect(prompt).toContain("14.7 秒以内");
      expect(prompt).toContain("元の文:「印刷すると消します。」");
      expect(prompt).toContain("変更後:「印刷が済むと消します。」");
      expect(prompt).toContain("10 → 11");
    });

    it("一番長い原稿でも 800 字に収まる", () => {
      const long = "あ".repeat(120);
      const p = consultPrompt({
        index: 12,
        title: "締め",
        budget: 19.7,
        original: long,
        edited: long,
      });
      expect(Array.from(p).length).toBeLessThan(800);
    });
  });
});

describe("原稿の変更の保存", () => {
  let root;
  let file;

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), "voice-edit-"));
    file = join(root, "sub", "edits.json");
  });

  afterEach(() => rmSync(root, { recursive: true, force: true }));

  it("ファイルが無ければ空", () => {
    expect(loadScriptEdits(file)).toEqual({});
  });

  it("元の文・変更後の文・日時を保存する", () => {
    saveScriptEdit(file, "b06", "元", "変更後", new Date(0));
    expect(loadScriptEdits(file)).toEqual({
      b06: {
        original: "元",
        edited: "変更後",
        updatedAt: "1970-01-01T00:00:00.000Z",
      },
    });
  });

  it("他の場面の変更を消さない", () => {
    saveScriptEdit(file, "b06", "元", "変更6", new Date(0));
    saveScriptEdit(file, "b09", "元", "変更9", new Date(0));
    expect(Object.keys(loadScriptEdits(file))).toEqual(["b06", "b09"]);
  });

  it("元の文に戻すと記録を消す", () => {
    saveScriptEdit(file, "b06", "元", "変更後", new Date(0));
    saveScriptEdit(file, "b06", "元", "元", new Date(0));
    expect(loadScriptEdits(file)).toEqual({});
  });

  it("空の文と不正な場面は保存しない", () => {
    expect(() =>
      saveScriptEdit(file, "b06", "元", "  \n", new Date(0)),
    ).toThrow();
    expect(() =>
      saveScriptEdit(file, "../x", "元", "文", new Date(0)),
    ).toThrow();
    expect(existsSync(file)).toBe(false);
  });

  it("改行は除いて保存する", () => {
    saveScriptEdit(file, "b06", "元", "一文目。\n二文目。", new Date(0));
    expect(loadScriptEdits(file).b06.edited).toBe("一文目。二文目。");
  });
});
