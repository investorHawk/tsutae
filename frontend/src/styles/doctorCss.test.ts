// @vitest-environment node
/**
 * 医師画面の色の約束（医師画面の UX の見直し）。jsdom は CSS を当てないので、変数の値と
 * 規則の中身を検査する。文字は 4.5:1、枠や線は 3:1 以上（WCAG 1.4.3・1.4.11）。
 * 色の意味は患者画面とそろえる（ある・つらい・受診日の線は patient.css と同じ値）。
 */
import { beforeAll, describe, expect, it } from "vitest";

interface Fs {
  readFileSync(path: URL, encoding: "utf8"): string;
}

let doctorCss = "";
let boardCss = "";
let uiCss = "";
let patientCss = "";
let panelsCss = "";

beforeAll(async () => {
  // vitest は CSS の import を空にするので、node の fs で直接読む（patientCss.test.ts と同じ）
  const fs = (await import(/* @vite-ignore */ `node:${"fs"}`)) as Fs;
  const read = (path: string) =>
    fs.readFileSync(new URL(path, import.meta.url), "utf8");
  doctorCss = read("./doctor.css");
  patientCss = read("./patient.css");
  boardCss = read("../components/doctor/board.css");
  uiCss = read("../components/doctor/doctor-ui.css");
  panelsCss = read("../components/doctor/regimen/regimen-panels.css");
});

function varOf(css: string, name: string): string {
  const match = new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, "i").exec(css);
  if (!match?.[1]) {
    throw new Error(`${name} is missing`);
  }
  return match[1].toLowerCase();
}

const d = (name: string) => varOf(doctorCss, name);

function ruleOf(css: string, selector: string): string {
  const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const match of code.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const selectors = (match[1] ?? "").split(",").map((x) => x.trim());
    if (selectors.includes(selector)) {
      return match[2] ?? "";
    }
  }
  return "";
}

function rgbOf(hex: string): [number, number, number] {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return [r!, g!, b!];
}

function contrast(a: string, b: string): number {
  const lum = (hex: string) => {
    const [r, g, b] = rgbOf(hex).map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

describe("医師画面の色の比", () => {
  it.each([
    ["ある（淡い青の地に紺）", "--d-yes-text", "--d-yes-bg"],
    ["つらい（紺の地に白）", "--d-hard-text", "--d-hard-bg"],
    ["なし（薄い灰の —）", "--d-none-text", "--d-bg"],
    ["要確認（橙の地に濃い橙）", "--d-warn-text", "--d-warn-bg"],
    ["代理（紫の地に紫）", "--d-proxy-text", "--d-proxy-bg"],
    ["受診日の文字（白の地に緑）", "--d-visit", "--d-bg"],
    ["無効の主ボタン（灰の地）", "--d-disabled-text", "--d-disabled-bg"],
  ])("文字 %s は 4.5:1 以上", (_label, text, bg) => {
    expect(contrast(d(text), d(bg))).toBeGreaterThanOrEqual(4.5);
  });

  it.each([
    ["要確認の枠（白の地）", "--d-warn-border", "--d-bg"],
    ["要確認の枠（橙の地）", "--d-warn-border", "--d-warn-bg"],
    ["受診日の線（白の地）", "--d-visit", "--d-bg"],
  ])("枠・線 %s は 3:1 以上", (_label, line, bg) => {
    expect(contrast(d(line), d(bg))).toBeGreaterThanOrEqual(3);
  });

  it("要確認は橙（赤 > 緑 > 青）", () => {
    for (const name of ["--d-warn-bg", "--d-warn-border", "--d-warn-text"]) {
      const [r, g, b] = rgbOf(d(name));
      expect(r).toBeGreaterThan(g);
      expect(g).toBeGreaterThan(b);
    }
  });
});

describe("患者画面と色の意味をそろえる", () => {
  it("受診日の線は患者画面と同じ緑", () => {
    expect(d("--d-visit")).toBe(varOf(patientCss, "--p-visit"));
  });

  it("要確認の地と枠は、患者画面の未入力の橙と同じ", () => {
    expect(d("--d-warn-bg")).toBe(varOf(patientCss, "--p-choice-prompt"));
    expect(d("--d-warn-border")).toBe(
      varOf(patientCss, "--p-choice-prompt-border"),
    );
  });

  it("代理は患者画面の代理入力と同じ紫", () => {
    expect(d("--d-proxy-bg")).toBe(varOf(patientCss, "--p-proxy-bg"));
  });
});

describe("経過表と注意の規則が変数を使う", () => {
  it("ある・つらい・なし・代理のセル", () => {
    const present = ruleOf(
      boardCss,
      ".doctor-app .d-grid td.d-grid-cell--present",
    );
    expect(present).toMatch(/background:\s*var\(--d-yes-bg\)/);
    expect(present).toMatch(/color:\s*var\(--d-yes-text\)/);
    const hard = ruleOf(boardCss, ".doctor-app .d-grid td.d-grid-cell--hard");
    expect(hard).toMatch(/background:\s*var\(--d-hard-bg\)/);
    expect(hard).toMatch(/color:\s*var\(--d-hard-text\)/);
    expect(hard).toMatch(/font-weight:\s*700/);
    expect(
      ruleOf(boardCss, ".doctor-app .d-grid td.d-grid-cell--none"),
    ).toMatch(/color:\s*var\(--d-none-text\)/);
    expect(
      ruleOf(boardCss, ".doctor-app .d-grid td.d-grid-cell--proxy"),
    ).toMatch(/background:\s*var\(--d-proxy-bg\)/);
  });

  it("受診日の線は 3px の緑", () => {
    const line = ruleOf(boardCss, ".doctor-app .d-grid-visit-line::before");
    expect(line).toMatch(/height:\s*3px/);
    expect(line).toMatch(/background:\s*var\(--d-visit\)/);
  });

  it("表は横にはみ出す時だけ表を横に送る", () => {
    expect(ruleOf(boardCss, ".doctor-app .d-grid-scroll")).toMatch(
      /overflow-x:\s*auto/,
    );
  });

  it("注意の帯・印は橙の変数（黄色の直書きを残さない）", () => {
    expect(ruleOf(uiCss, ".doctor-app .d-notice")).toMatch(
      /var\(--d-warn-bg\)/,
    );
    expect(ruleOf(uiCss, ".doctor-app .d-badge--warn")).toMatch(
      /var\(--d-warn-text\)/,
    );
    expect(ruleOf(boardCss, ".doctor-app .d-flag")).toMatch(
      /var\(--d-warn-border\)/,
    );
    expect(uiCss).not.toMatch(/#c9a227|#ffe9a8|#fff8e5/i);
  });
});

describe("主ボタンの無効の見た目", () => {
  const PRIMARY = ".doctor-app button.d-primary";

  it("押せないときは灰色（紺のままにしない）", () => {
    const rule = ruleOf(doctorCss, `${PRIMARY}:disabled`);
    expect(rule).toMatch(/color:\s*var\(--d-disabled-text\)/);
    expect(rule).toMatch(/background:\s*var\(--d-disabled-bg\)/);
    expect(rule).toMatch(/border-color:\s*var\(--d-disabled-bg\)/);
    const [r, g, b] = rgbOf(d("--d-disabled-bg"));
    expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThanOrEqual(10);
  });

  it("hover でも変わらない（主ボタンの hover の規則が無い）", () => {
    for (const css of [doctorCss, uiCss, panelsCss]) {
      expect(css).not.toMatch(/\.d-primary[^{]*:hover/);
    }
  });
});

describe("チャットの枠", () => {
  const CHAT = ".doctor-app .rf-chat";

  it("高さと sticky の位置は useChatFit の変数（下の値は変数が入るまでの保険）", () => {
    const rule = ruleOf(panelsCss, CHAT);
    expect(rule).toMatch(/top:\s*var\(--rf-chat-top\);/);
    expect(rule).toMatch(
      /height:\s*var\(--rf-chat-h,\s*calc\(100vh - 64px\)\)/,
    );
    expect(rule).toMatch(/min-height:\s*320px/);
    expect(rule).toMatch(/max-height:\s*960px/);
  });

  it("会話が縮んでスクロールし、入力欄は縮まない", () => {
    const log = ruleOf(panelsCss, ".doctor-app .rf-chat-log");
    expect(log).toMatch(/min-height:\s*0/);
    expect(log).toMatch(/overflow-y:\s*auto/);
    expect(ruleOf(panelsCss, ".doctor-app .rf-chat-input")).toMatch(
      /flex:\s*0 0 auto/,
    );
  });

  it("狭い画面では今までどおり高さを決めない（基本の規則より後ろで上書きする）", () => {
    const at = panelsCss.indexOf("@media (max-width: 960px)");
    expect(at).toBeGreaterThan(panelsCss.indexOf(`${CHAT} {`));
    const narrow = panelsCss.slice(at);
    expect(narrow).toMatch(
      /\.rf-chat \{[^}]*position:\s*static;[^}]*height:\s*auto;[^}]*min-height:\s*0;/,
    );
  });
});
