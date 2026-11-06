import { describe, expect, it } from "vitest";
import {
  buildSubtitleChunks,
  chunkAt,
  LINE_MAX,
  splitSentences,
  wrapLines,
} from "../src/lib/subtitle";
import { STORYBOARDS } from "../src/storyboards";
import { countChars } from "../src/lib/text";

describe("字幕の分割", () => {
  it("句点で文に分け、括弧の中の句点では分けない", () => {
    expect(splitSentences("つたえ。化学療法の記録です。")).toEqual([
      "つたえ。",
      "化学療法の記録です。",
    ]);
    expect(splitSentences("「下痢はいつ。」「えっと」。次")).toEqual([
      "「下痢はいつ。」",
      "「えっと」。",
      "次",
    ]);
  });

  it("短い塊は 1 行、長い塊は 2 行に折り、行頭に読点を置かない", () => {
    expect(wrapLines("診察室の 3 分を、30 秒に。")).toHaveLength(1);
    const lines = wrapLines(
      "外来化学療法の診察では、医師が 2 週間分の症状を 3 分ほどかけて聞き取ります。",
    );
    expect(lines).toHaveLength(2);
    for (const l of lines) expect(/^[、。」]/.test(l)).toBe(false);
  });

  it("時間の配分は 0 から 1 まで切れ目なく並ぶ", () => {
    const chunks = buildSubtitleChunks(
      "つたえ。化学療法中の 2 週間の記録を、診察室の A4 一枚にするアプリです。",
    );
    expect(chunks[0].start).toBe(0);
    expect(chunks[chunks.length - 1].end).toBeCloseTo(1);
    chunks.slice(1).forEach((c, i) => expect(c.start).toBe(chunks[i].end));
  });

  it("ひらがなの直前では切らない（「」の直後の助詞・語の途中）", () => {
    expect(
      wrapLines(
        "「おとといの夜から口内炎」は Day5 の口内炎として、原文の引用つきで載ります。",
      )[1].startsWith("は"),
    ).toBe(false);
    const breaks: string[] = [];
    for (const { scenes } of STORYBOARDS) {
      for (const s of scenes) {
        const lines = buildSubtitleChunks(s.caption ?? s.narration).flatMap(
          (c) => c.lines,
        );
        lines.slice(1).forEach((l, i) => {
          const prev = Array.from(lines[i].trim()).pop() ?? "";
          const next = Array.from(l.trim())[0] ?? "";
          if (/[\u3041-\u309F]/.test(next) && !/[、。！？]/.test(prev)) {
            breaks.push(`${s.id}: ${lines[i]} / ${l}`);
          }
        });
      }
    }
    expect(breaks).toEqual([]);
  });

  it("全案の全字幕が 2 行以内・1 行 30 字以内に収まり、文字を落とさない", () => {
    for (const { scenes } of STORYBOARDS) {
      for (const s of scenes) {
        const chunks = buildSubtitleChunks(s.caption ?? s.narration);
        const joined = chunks.flatMap((c) => c.lines).join("");
        expect(countChars(joined), s.id).toBe(
          countChars(s.caption ?? s.narration),
        );
        for (const c of chunks) {
          expect(c.lines.length, s.id).toBeLessThanOrEqual(2);
          for (const l of c.lines) {
            expect(countChars(l), `${s.id}: ${l}`).toBeLessThanOrEqual(
              LINE_MAX + 2,
            );
            expect(/^[、。」]/.test(l), `${s.id}: ${l}`).toBe(false);
          }
        }
      }
    }
  });
});

describe("字幕の塊を出す時刻", () => {
  const chunks = buildSubtitleChunks(
    "つたえ。化学療法中の 2 週間の記録を、診察室の A4 一枚にするアプリです。",
  );

  it("塊を場面全体に配る", () => {
    expect(chunkAt(chunks, 0, 100)).toEqual({ index: 0, startFrame: 0 });
    const lastStart = chunks[chunks.length - 1].start * 100;
    expect(chunkAt(chunks, Math.ceil(lastStart), 100)).toEqual({
      index: chunks.length - 1,
      startFrame: lastStart,
    });
  });

  it("場面の終わりより後は最後の塊を出し続ける", () => {
    expect(chunkAt(chunks, 100, 100).index).toBe(chunks.length - 1);
    expect(chunkAt(chunks, 130, 100).index).toBe(chunks.length - 1);
  });
});
