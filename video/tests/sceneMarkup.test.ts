// ブラウザを使わず、場面を HTML の文字列に描いて中身を確かめる（見た目はここでは確かめない）。
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FootageScene } from "../src/scenes/FootageScene";
import { IntroScene } from "../src/scenes/IntroScene";
import { NOTES_AT, NotesScene } from "../src/scenes/NotesScene";
import { scenesB } from "../src/storyboards";
import type { Scene } from "../src/types";

const mocks = vi.hoisted(() => ({
  frame: 0,
  screenFiles: {} as Record<string, string[]>,
  portraitFile: null as string | null,
}));

vi.mock("remotion", async (importOriginal) => ({
  ...(await importOriginal<typeof import("remotion")>()),
  useCurrentFrame: () => mocks.frame,
  useVideoConfig: () => ({ fps: 30 }),
  Sequence: ({ children }: { children: ReactNode }) => children,
  Img: ({ src }: { src: string }) => `写真 ${src}`,
  staticFile: (path: string) => path,
}));

vi.mock("../src/footage.generated", () => ({
  footageFiles: {},
  screenFiles: mocks.screenFiles,
  bgmFile: null,
  voiceFiles: {},
  get portraitFile() {
    return mocks.portraitFile;
  },
}));

vi.mock("../src/components/ScreenSlides", () => ({
  ScreenSlides: ({ files }: { files: string[] }) => `静止画 ${files.join(",")}`,
}));

const sceneOf = (id: string): Scene => {
  const scene = scenesB.find((s) => s.id === id);
  if (!scene) throw new Error(`場面が無い: ${id}`);
  return scene;
};

const markup = (component: typeof NotesScene, id: string, frame: number) => {
  mocks.frame = frame;
  const scene = sceneOf(id);
  return renderToStaticMarkup(
    createElement(component, {
      scene,
      durationInFrames: scene.seconds * 30,
      variant: "b",
    }),
  );
};

/** text を含む要素（の最も内側の開始タグ）の透明度 */
const opacityOf = (html: string, text: string): number => {
  const before = html.slice(0, html.indexOf(text));
  const tag = before.slice(before.lastIndexOf("<"));
  const m = /opacity:([\d.]+)/.exec(tag);
  return m ? Number(m[1]) : 1;
};

describe("NotesScene の 3 段階", () => {
  const duration = 16 * 30;
  const frameAt = (ratio: number) => Math.round(duration * ratio);

  it("1 段階目: ノート 3 冊（svg）と札。負担の札はまだ出ない", () => {
    const html = markup(NotesScene, "b03-notes", frameAt(NOTES_AT.label) + 12);
    expect(html.match(/<svg/g)).toHaveLength(3);
    expect(opacityOf(html, "書式はまちまち")).toBe(1);
    expect(opacityOf(html, "患者さん: 書き方を学ぶ")).toBe(0);
    expect(opacityOf(html, "医師: 読むのに時間がかかる")).toBe(0);
  });

  it("レジメンの説明は、声の頭から 2 段階目まで出て、3 段階目で消える", () => {
    const text = "＝抗がん剤の種類と投与の仕方";
    expect(opacityOf(markup(NotesScene, "b03-notes", 20), text)).toBe(1);
    expect(
      opacityOf(
        markup(NotesScene, "b03-notes", frameAt(NOTES_AT.answer) - 1),
        text,
      ),
    ).toBe(1);
    expect(markup(NotesScene, "b03-notes", duration - 1)).toContain(
      "opacity:0",
    );
  });

  it("2 段階目: 負担の札が順に出る", () => {
    const first = frameAt(NOTES_AT.burdens[0]) + 12;
    const second = frameAt(NOTES_AT.burdens[1]) + 12;
    const html = markup(NotesScene, "b03-notes", first);
    expect(opacityOf(html, "患者さん: 書き方を学ぶ")).toBe(1);
    expect(opacityOf(html, "医師: 読むのに時間がかかる")).toBe(0);
    expect(
      opacityOf(
        markup(NotesScene, "b03-notes", second),
        "医師: 読むのに時間がかかる",
      ),
    ).toBe(1);
  });

  it("3 段階目: 前の段階は消え、文と名前が紺で強調される", () => {
    const html = markup(NotesScene, "b03-notes", duration - 1);
    expect(opacityOf(html, "患者さんにも医師にも使いやすいアプリへ")).toBe(1);
    expect(opacityOf(html, "つたえ")).toBe(1);
    expect(html).toContain("opacity:0"); // 前の段階の包み
    expect(html).toContain("#0b4a9c");
  });

  it("実在の名前を思わせる文字を描かない（ノートの中は線と枠だけ）", () => {
    const html = markup(NotesScene, "b03-notes", 60);
    expect(html.match(/<svg[\s\S]*?<\/svg>/g)?.join("")).not.toContain("<text");
  });
});

describe("b01-intro の先生の写真", () => {
  beforeEach(() => {
    mocks.portraitFile = null;
  });

  it("写真が無ければ出さず、文字は中央のまま", () => {
    const html = markup(IntroScene, "b01-intro", 100);
    expect(html).not.toContain("写真 ");
    expect(html).not.toContain("padding-left");
  });

  it("写真があれば出し、文字を右に寄せる", () => {
    mocks.portraitFile = "private/portrait.jpg";
    const html = markup(IntroScene, "b01-intro", 100);
    expect(html).toContain("写真 private/portrait.jpg");
    expect(html).toContain("padding-left");
  });
});

describe("録画の場面の札と F11", () => {
  beforeEach(() => {
    for (const key of Object.keys(mocks.screenFiles)) {
      delete mocks.screenFiles[key];
    }
    mocks.screenFiles.F1 = ["screens/F1-1.png"];
    mocks.screenFiles.F2 = ["screens/F2-1.png"];
    mocks.screenFiles.F4 = ["screens/F4-1.png", "screens/F4-2.png"];
  });

  it("b06: 場面の前半は 1 つ目の札、後半は 2 つ目の札", () => {
    const early = markup(FootageScene, "b06-visit", 224);
    expect(early).toContain("患者さんの画面に AI の文は出ない");
    expect(early).not.toContain("記録はスマホに保存");
    const late = markup(FootageScene, "b06-visit", 225);
    expect(late).toContain("記録はスマホに保存。印刷すると消す");
    expect(late).not.toContain("患者さんの画面に AI の文は出ない");
  });

  it("b09: 札はレジメンの説明 → JSON → 確かめて採用の順に出る", () => {
    mocks.screenFiles.F8 = ["screens/F8-1.png"];
    const at = (frame: number) => markup(FootageScene, "b09-regimen", frame);
    expect(at(30)).toContain("レジメン＝抗がん剤の種類と投与の仕方");
    expect(at(200)).toContain("JSON がわからなくても、AI が指示どおりに設定");
    expect(at(400)).toContain("入れた値は、医師が確かめてから採用");
  });

  it("b05: F11 の静止画が無ければ、撮影枠のカードに置き場所を出す", () => {
    const html = markup(FootageScene, "b05-patient", 400);
    expect(html).toContain("撮影枠");
    expect(html).toContain("patient_reminder");
    expect(html).toContain("video/public/screens/F11-1.png");
    expect(html).not.toContain("video/public/footage/F11.mp4");
  });

  it("b05: F11 の静止画を置くと、スマホの枠に見出しと 3 つ目の札が出る", () => {
    mocks.screenFiles.F11 = ["screens/F11-1.png"];
    const html = markup(FootageScene, "b05-patient", 400);
    expect(html).not.toContain("撮影枠");
    expect(html).toContain("静止画 screens/F11-1.png");
    expect(html).toContain("毎日のお知らせ");
    expect(html).toContain("決めた時刻にお知らせ。書き忘れと言い忘れが減る");
  });
});
