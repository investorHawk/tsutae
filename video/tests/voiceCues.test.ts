import { describe, expect, it } from "vitest";
import { buildSubtitleChunks, timeChunks } from "../src/lib/subtitle";
import {
  contentFrames,
  VOICE_OFFSET_SECONDS,
  voiceKeyOf,
} from "../src/lib/voice";
import { scenesB } from "../src/storyboards";
import { VOICE_CUES } from "../src/storyboards/bVoiceCues";

describe("声の実測（bVoiceCues。scripts/voice_cues.py が書く）", () => {
  it.each(scenesB.map((s) => [s.id, s] as const))("%s", (_id, scene) => {
    const cue = VOICE_CUES[voiceKeyOf(scene.id)];
    const chunks = buildSubtitleChunks(scene.caption ?? scene.narration);
    // 字幕の塊ごとに、声の中での開始がある
    expect(cue.starts).toHaveLength(chunks.length);
    cue.starts.forEach((t, i) => {
      if (i > 0) expect(t).toBeGreaterThan(cue.starts[i - 1]);
      expect(t).toBeLessThan(cue.seconds);
    });
    // 声は次の場面に重ならない
    expect(VOICE_OFFSET_SECONDS + cue.seconds).toBeLessThanOrEqual(
      scene.seconds,
    );
  });
});

describe("timeChunks（字幕を実際の声に合わせる）", () => {
  const chunks = buildSubtitleChunks(
    "一文目です。二文目もあります。三文目はこれで、終わりになります。とても長い文にしておきます。",
  );

  it("塊の頭を実測の時刻に置き、最初は場面の頭、最後は場面の終わりまで", () => {
    const starts = chunks.map((_, i) => i * 2);
    const timed = timeChunks(chunks, starts, 20);
    expect(timed[0].start).toBe(0);
    expect(timed[timed.length - 1].end).toBe(1);
    timed.slice(1).forEach((c, i) => {
      expect(c.start).toBeCloseTo((VOICE_OFFSET_SECONDS + starts[i + 1]) / 20);
      expect(c.start).toBe(timed[i].end);
    });
  });

  it("元の配列を書き換えず、数が合わなければそのまま返す", () => {
    const before = JSON.stringify(chunks);
    expect(timeChunks(chunks, [0], 20)).toEqual(chunks);
    timeChunks(
      chunks,
      chunks.map((_, i) => i),
      20,
    );
    expect(JSON.stringify(chunks)).toBe(before);
  });
});

describe("contentFrames（演出の基準を声の長さにする）", () => {
  it("声があれば、声の終わりまでのフレーム数", () => {
    expect(contentFrames(300, 5, 30)).toBe(
      Math.round((VOICE_OFFSET_SECONDS + 5) * 30),
    );
  });

  it("声が無ければ場面の長さのまま、場面より長くはしない", () => {
    expect(contentFrames(300, undefined, 30)).toBe(300);
    expect(contentFrames(300, 60, 30)).toBe(300);
  });
});
