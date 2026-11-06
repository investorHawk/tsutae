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

describe("各案の尺", () => {
  const byId = (id: string) =>
    STORYBOARDS.find((sb) => sb.compositionId === id);

  it("DemoB は 165 秒・11 場面", () => {
    expect(byId("DemoB")?.seconds).toBe(165);
    expect(byId("DemoB")?.scenes).toHaveLength(11);
  });

  it("先生の声（public/voice/）の印があるのは DemoB だけ", () => {
    expect(
      STORYBOARDS.filter((sb) => sb.voice === true).map(
        (sb) => sb.compositionId,
      ),
    ).toEqual(["DemoB"]);
  });

  it("DemoA と DemoC は 150 秒", () => {
    expect(byId("DemoA")?.seconds).toBe(150);
    expect(byId("DemoC")?.seconds).toBe(150);
  });
});

/** (5) の利点の言葉。案 B は 2026-11-06 の先生の実感値（2 分 → 20 秒）、案 A・C は前の 3 分 → 30 秒 */
const BENEFIT_WORDS: Record<string, string[]> = {
  DemoA: ["言い忘れ", "30 秒"],
  DemoB: ["言い忘れ", "20 秒"],
  DemoC: ["言い忘れ", "30 秒"],
};

describe.each(STORYBOARDS)(
  "$compositionId（$title）",
  ({ compositionId, scenes, seconds }) => {
    it("(1) 場面の秒数の合計が sb.seconds、フレームが sb.seconds × 30", () => {
      expect(totalSeconds(scenes)).toBe(seconds);
      expect(totalFrames(scenes, FPS)).toBe(seconds * 30);
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

    // 150 秒なら 450〜800 字、165 秒なら 495〜880 字（3〜約 5.3 字/秒）
    it("(4) 字幕の文（narration）の合計字数が尺に比例した範囲（空白を除く）", () => {
      const total = scenes.reduce((sum, s) => sum + countChars(s.narration), 0);
      expect(total).toBeGreaterThanOrEqual(seconds * 3);
      expect(total).toBeLessThanOrEqual(Math.round((seconds * 16) / 3));
    });

    it("(5) 利点の言葉（「言い忘れ」と、案ごとの聞き取りの秒数）を含む", () => {
      const all = scenes.map((s) => s.narration).join("");
      const words = BENEFIT_WORDS[compositionId] ?? [];
      expect(words.length, compositionId).toBeGreaterThan(0);
      for (const w of words) expect(all, w).toContain(w);
    });

    it("場面ごとの必須の props がある", () => {
      for (const s of scenes) {
        if (s.kind === "report")
          expect(s.props?.focus?.length, s.id).toBeGreaterThan(0);
        if (s.kind === "closing") {
          const count =
            (s.props?.stats?.length ?? 0) +
            (s.props?.compare?.items.length ?? 0);
          expect(count, s.id).toBeGreaterThan(0);
        }
        if (s.kind === "intro") {
          expect(s.props?.career?.length, s.id).toBeGreaterThan(0);
          expect(s.props?.lines?.length, s.id).toBeGreaterThan(0);
        }
        if (s.kind === "whypaper") {
          expect(s.props?.barriers?.length, s.id).toBeGreaterThan(0);
          expect(s.props?.gains?.length, s.id).toBeGreaterThan(0);
        }
        if (s.kind === "promises") {
          expect(s.props?.dont, s.id).toHaveLength(5);
          expect(s.props?.privacy, s.id).toHaveLength(3);
        }
      }
    });
  },
);

describe("案 B（DemoB）の聞き取りの時間（2 分 → 20 秒）", () => {
  const b = STORYBOARDS.find((sb) => sb.compositionId === "DemoB");
  const scenes = b?.scenes ?? [];
  const byKind = (kind: string) => scenes.find((s) => s.kind === kind);

  it("before の時計は 120 秒、after の時計は 20 秒", () => {
    expect(byKind("before")?.props?.clockSeconds).toBe(120);
    expect(byKind("after")?.props?.clockSeconds).toBe(20);
  });

  it("closing は棒グラフ（2 行以上）・事実（1 つ以上）・最後の文 2 つ", () => {
    const props = byKind("closing")?.props;
    expect(props?.stats).toBeUndefined();
    expect(props?.compare?.items.length).toBeGreaterThanOrEqual(2);
    expect(props?.facts?.length).toBeGreaterThanOrEqual(1);
    expect(props?.messages).toHaveLength(2);
  });

  it("前の実感値（3 分・30 秒・3:00・0:30）が narration・screen・props のどこにも残っていない", () => {
    for (const s of [...scenes, { id: "title", title: b?.title }]) {
      const text = JSON.stringify(s);
      for (const old of ["3 分", "30 秒", "3:00", "0:30"]) {
        expect(text.includes(old), `${s.id}: ${old}`).toBe(false);
      }
    }
  });
});
