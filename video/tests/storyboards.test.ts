import { describe, expect, it } from "vitest";
import { FOOTAGE } from "../src/footage";
import { countChars } from "../src/lib/text";
import {
  footageSegments,
  totalFrames,
  totalSeconds,
} from "../src/lib/timeline";
import { STORYBOARDS } from "../src/storyboards";
import { FPS } from "../src/theme";

describe.each(STORYBOARDS)("$compositionId（$title）", ({ scenes }) => {
  it("(1) 場面の秒数の合計がちょうど 150 秒・4500 フレーム", () => {
    expect(totalSeconds(scenes)).toBe(150);
    expect(totalFrames(scenes, FPS)).toBe(4500);
  });

  it("(2) 各場面の秒数は 1 以上の整数", () => {
    for (const s of scenes) {
      expect(Number.isInteger(s.seconds), s.id).toBe(true);
      expect(s.seconds, s.id).toBeGreaterThanOrEqual(1);
    }
  });

  it("場面の id が重ならない", () => {
    const ids = scenes.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  // (3) 録画を使う場面の秒数は撮影リストの最低秒以下。
  // kind "footage" は区間の合計 = 場面の秒数。masking（案 C の F4）は録画を場面の一部だけに出し、
  // 残りは伏せ字のアニメだけにするので「区間の合計 ≤ 場面の秒数」とする（F4 の最低秒 10 < 場面 14 秒）。
  // pipeline の背景の F7 は props.backgroundFootage（任意・ループ）で、footage には入れない。
  it("(3) 録画の区間は最低秒以下で、場面の秒数に収まる", () => {
    for (const s of scenes.filter((x) => (x.footage ?? []).length > 0)) {
      const segs = footageSegments(s);
      const ids = s.footage ?? [];
      if (ids.length > 1 || s.props?.split) {
        expect(s.props?.split?.length, `${s.id} split`).toBe(ids.length);
      }
      const sum = segs.reduce((a, g) => a + g.seconds, 0);
      if (s.kind === "footage") expect(sum, s.id).toBe(s.seconds);
      else expect(sum, s.id).toBeLessThanOrEqual(s.seconds);
      for (const g of segs) {
        expect(Number.isInteger(g.seconds), `${s.id} ${g.id}`).toBe(true);
        expect(g.seconds, `${s.id} ${g.id}`).toBeGreaterThanOrEqual(1);
        expect(g.seconds, `${s.id} ${g.id}`).toBeLessThanOrEqual(
          FOOTAGE[g.id].minSeconds,
        );
      }
    }
  });

  it("footage の場面は footage を持ち、それ以外で持つのは masking だけ", () => {
    for (const s of scenes) {
      const has = (s.footage ?? []).length > 0;
      if (s.kind === "footage") expect(has, s.id).toBe(true);
      else if (has) expect(s.kind, s.id).toBe("masking");
    }
  });

  it("(4) 字幕の文（narration）の合計字数が 450〜800 字（空白を除く）", () => {
    const total = scenes.reduce((sum, s) => sum + countChars(s.narration), 0);
    expect(total).toBeGreaterThanOrEqual(450);
    expect(total).toBeLessThanOrEqual(800);
  });

  it("(5) 利点の言葉「言い忘れ」と「30 秒」を含む", () => {
    const all = scenes.map((s) => s.narration).join("");
    expect(all).toContain("言い忘れ");
    expect(all).toContain("30 秒");
  });

  it("場面ごとの必須の props がある", () => {
    for (const s of scenes) {
      if (s.kind === "report")
        expect(s.props?.focus?.length, s.id).toBeGreaterThan(0);
      if (s.kind === "closing")
        expect(s.props?.stats?.length, s.id).toBeGreaterThan(0);
      if (s.kind === "promises") {
        expect(s.props?.dont, s.id).toHaveLength(5);
        expect(s.props?.privacy, s.id).toHaveLength(3);
      }
    }
  });
});
