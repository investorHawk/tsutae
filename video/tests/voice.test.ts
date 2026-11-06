import { describe, expect, it } from "vitest";
import { layoutScenes } from "../src/lib/timeline";
import {
  VOICE_OFFSET_SECONDS,
  voiceKeyOf,
  voiceTracks,
} from "../src/lib/voice";
import { scenesA, scenesB } from "../src/storyboards";
import type { Scene } from "../src/types";

const fps = 30;

const scene = (id: string, seconds: number): Scene => ({
  id,
  seconds,
  kind: "title",
  narration: "つたえ。",
});

describe("voiceKeyOf（場面 id の頭）", () => {
  it("最初の - より前を小文字で返す", () => {
    expect(voiceKeyOf("b01-intro")).toBe("b01");
    expect(voiceKeyOf("B11-closing")).toBe("b11");
    expect(voiceKeyOf("b05")).toBe("b05");
  });
});

describe("voiceTracks（声のある場面ごとの再生の頭）", () => {
  const timed = layoutScenes(
    [scene("b01-x", 10), scene("b02-y", 5), scene("b03-z", 4)],
    fps,
  );

  it("声のある場面だけを、場面の頭 + 0.3 秒から鳴らす", () => {
    expect(VOICE_OFFSET_SECONDS).toBe(0.3);
    const tracks = voiceTracks(
      timed,
      { b01: "voice/b01.m4a", b03: "voice/b03_end.wav" },
      fps,
    );
    expect(tracks).toEqual([
      { key: "b01", src: "voice/b01.m4a", from: 9 },
      { key: "b03", src: "voice/b03_end.wav", from: 450 + 9 },
    ]);
  });

  it("声が無ければ空", () => {
    expect(voiceTracks(timed, {}, fps)).toEqual([]);
  });

  it("引数を書き換えない", () => {
    const files = { b02: "voice/b02.mp3" };
    const before = JSON.stringify({ timed, files });
    voiceTracks(timed, files, fps);
    expect(JSON.stringify({ timed, files })).toBe(before);
  });

  it("案 B の声は案 A の場面に当たらない（キーは場面 id の頭）", () => {
    const files = Object.fromEntries(
      scenesB.map((s) => [voiceKeyOf(s.id), `voice/${voiceKeyOf(s.id)}.m4a`]),
    );
    expect(voiceTracks(layoutScenes(scenesA, fps), files, fps)).toEqual([]);
    expect(voiceTracks(layoutScenes(scenesB, fps), files, fps)).toHaveLength(
      11,
    );
  });
});
