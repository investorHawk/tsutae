import { describe, expect, it } from "vitest";
import { FOOTAGE } from "../src/footage";
import { buildSubtitleChunks } from "../src/lib/subtitle";
import { VOICE_OFFSET_SECONDS } from "../src/lib/voice";
import { VOICE_CUES } from "../src/storyboards/bVoiceCues";
import { countChars } from "../src/lib/text";
import {
  footageSegments,
  totalFrames,
  totalSeconds,
} from "../src/lib/timeline";
import { NOTES_AT } from "../src/scenes/NotesScene";
import { STORYBOARDS } from "../src/storyboards";
import { FPS } from "../src/theme";

describe("各案の尺", () => {
  const byId = (id: string) =>
    STORYBOARDS.find((sb) => sb.compositionId === id);

  it("DemoB は 175 秒・12 場面", () => {
    expect(byId("DemoB")?.seconds).toBe(175);
    expect(byId("DemoB")?.scenes).toHaveLength(12);
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
    // 残りは伏せ字のアニメだけにするので「区間の合計 ≤ 場面の秒数」とする（案 C の F4 は 10 秒 < 場面 14 秒）。
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

    // 150 秒なら 450〜800 字、175 秒なら 525〜933 字（3〜約 5.3 字/秒）
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
        if (s.kind === "notes") {
          expect(s.props?.formatLabel, s.id).toBeTruthy();
          expect(s.props?.burdens, s.id).toHaveLength(2);
          expect(s.props?.answer, s.id).toBeTruthy();
          expect(s.props?.brand, s.id).toBeTruthy();
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

describe("案 B（DemoB）の 175 秒の構成", () => {
  const scenes =
    STORYBOARDS.find((sb) => sb.compositionId === "DemoB")?.scenes ?? [];
  const byId = (id: string) => scenes.find((s) => s.id === id);

  it("場面の id・秒・種類は承認された順のとおり", () => {
    expect(scenes.map((s) => [s.id, s.seconds, s.kind])).toEqual([
      ["b01-intro", 17, "intro"],
      ["b02-before", 14, "before"],
      ["b03-notes", 15, "notes"],
      ["b04-after", 12, "after"],
      ["b05-patient", 19, "footage"],
      ["b06-visit", 14, "footage"],
      ["b07-pipeline", 13, "pipeline"],
      ["b08-report", 16, "report"],
      ["b09-regimen", 14, "footage"],
      ["b10-whypaper", 11, "whypaper"],
      ["b11-promises", 7, "promises"],
      ["b12-closing", 23, "closing"],
    ]);
  });

  it.each([
    [
      "b03-notes",
      "レジメン別のノートは複数出ていますが、書式はまちまち。患者さんは書き方を学び、医師は読むのに時間がかかります。そこで、患者さんにも医師にも使いやすいアプリにしました。",
    ],
    [
      "b05-patient",
      "外来化学療法の患者さんは毎日スマホで、3 択と自由記載を記録します。つらい日はボタン 1 つ。抗がん剤が変わっても、入力の形は同じ。決めた時刻にお知らせが届き、書き忘れと言い忘れが減ります。",
    ],
    [
      "b06-visit",
      "受診日は、受付番号を入れて送るだけ。患者さんの画面に AI の文は出ません。記録はスマホに保存。サーバーへ送るのは受診のときだけで、印刷が済むと消します。",
    ],
    [
      "b07-pipeline",
      "人名などを伏せ字にした自由記載を、Claude Agent SDK が日付と症状の用語にそろえ、原文の引用つきの A4 一枚にします。",
    ],
    [
      "b09-regimen",
      "新しいレジメンも、医師がチャットから文で伝えるだけ。Claude Agent SDK が指示どおりに設定します。入れた値は、医師が確かめてから採用します。",
    ],
    [
      "b11-promises",
      "AI は、副作用の重さの判定や助言をしません。判断は医師が行います。",
    ],
  ])("%s の声は承認された文のまま", (id, narration) => {
    expect(byId(id)?.narration).toBe(narration);
  });

  it("b03-notes: 札の文は構成データから渡す。実在の名前は書かない", () => {
    const props = byId("b03-notes")?.props;
    expect(props?.formatLabel).toBe("書式はまちまち");
    expect(props?.burdens).toEqual([
      "患者さん: 書き方を学ぶ",
      "医師: 読むのに時間がかかる",
    ]);
    expect(props?.answer).toBe("患者さんにも医師にも使いやすいアプリへ");
    expect(props?.brand).toBe("つたえ");
  });

  it("b03-notes の札は声の位置（文字数の割合）で出る", () => {
    const narration = byId("b03-notes")?.narration ?? "";
    const ratioOf = (phrase: string) =>
      countChars(narration.slice(0, narration.indexOf(phrase))) /
      countChars(narration);
    expect(NOTES_AT.label).toBeCloseTo(ratioOf("書式は"), 2);
    expect(NOTES_AT.burdens[0]).toBeCloseTo(ratioOf("患者さんは"), 2);
    expect(NOTES_AT.burdens[1]).toBeCloseTo(ratioOf("医師は"), 2);
    expect(NOTES_AT.answer).toBeCloseTo(ratioOf("そこで"), 2);
  });

  it("b03-notes の字幕の塊の頭と、段階の切り替えがそろう", () => {
    const chunks = buildSubtitleChunks(byId("b03-notes")?.narration ?? "");
    expect(chunks).toHaveLength(3);
    expect(NOTES_AT.burdens[0]).toBeCloseTo(chunks[1].start, 2);
    expect(NOTES_AT.answer).toBeCloseTo(chunks[2].start, 2);
  });

  it("b05-patient は F1 → F2 → F11 を 7・5・7 秒で、札を 1 つずつ", () => {
    const scene = byId("b05-patient");
    expect(scene?.footage).toEqual(["F1", "F2", "F11"]);
    expect(scene?.props?.split).toEqual([7, 5, 7]);
    expect(scene?.props?.callouts).toEqual([
      "「おとといの夜から口内炎がいたい」",
      "抗がん剤が変わっても、入力の形は同じ",
      "決めた時刻にお知らせ。書き忘れと言い忘れが減る",
    ]);
  });

  it("b06-visit の 2 つ目の札は、声の「記録はスマホに」の頃に出る", () => {
    const scene = byId("b06-visit");
    expect(scene?.footage).toEqual(["F4"]);
    expect(scene?.props?.callouts).toEqual([
      "患者さんの画面に AI の文は出ない",
      "記録はスマホに保存。\nサーバーの分は\n印刷済みで消す",
    ]);
    const chunks = buildSubtitleChunks(scene?.narration ?? "");
    const at = chunks.findIndex((c) =>
      c.lines.join("").startsWith("記録はスマホ"),
    );
    // 札は場面の半分（F4 の 2 枚目の静止画の頭）で変わる。実際の声との差は 0.5 秒以内
    const voiceAt = VOICE_OFFSET_SECONDS + VOICE_CUES.b06.starts[at];
    expect(Math.abs(voiceAt - (scene?.seconds ?? 0) / 2)).toBeLessThan(0.5);
  });

  it("b07-pipeline は 58% の出典の注記を画面に残し、声からは外す", () => {
    const scene = byId("b07-pipeline");
    expect(scene?.props?.notes).toHaveLength(2);
    expect(scene?.props?.notes?.[1]).toContain("58%");
    expect(scene?.props?.notes?.[1]).toContain("Chung ら, JAMIA 2019");
    expect(scene?.narration).not.toContain("58%");
  });

  it("b02-before の会話は「変わりありませんでしたか」「下痢しました」から始まり、声は変えない", () => {
    const scene = byId("b02-before");
    expect(scene?.props?.bubbles?.slice(0, 3)).toEqual([
      { who: "doctor", text: "変わりありませんでしたか" },
      { who: "patient", text: "下痢しました" },
      { who: "doctor", text: "下痢はいつからでしたか" },
    ]);
    expect(scene?.narration).not.toContain("変わりありません");
  });

  it("b03-notes はレジメンの意味を札で説明する（声は変えない）", () => {
    const scene = byId("b03-notes");
    expect(scene?.props?.definition).toEqual([
      "レジメン",
      "＝抗がん剤の種類と投与の仕方",
    ]);
    expect(scene?.narration).toContain("レジメン別のノート");
  });

  it("b09-regimen はチャットの文から Claude Agent SDK が設定することを声と札で言い、確かめて採用も残す", () => {
    const scene = byId("b09-regimen");
    expect(scene?.narration).toContain(
      "Claude Agent SDK が指示どおりに設定します。",
    );
    expect(JSON.stringify(scene)).not.toContain("JSON");
    expect(scene?.narration).toContain("医師が確かめてから採用します");
    expect(scene?.props?.callouts).toEqual([
      "レジメン＝抗がん剤の種類と投与の仕方",
      "チャットで伝えると、\nClaude Agent SDK が指示どおりに設定",
      "入れた値は、医師が確かめてから採用",
    ]);
  });

  it("b11-promises の受付番号は、送らない相手が Claude だと分かる", () => {
    expect(byId("b11-promises")?.props?.privacy).toContain(
      "受付番号は Claude に送らない",
    );
  });

  it("b09-regimen は F8 だけ", () => {
    expect(byId("b09-regimen")?.footage).toEqual(["F8"]);
  });
});
