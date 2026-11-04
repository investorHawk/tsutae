// @vitest-environment node
/**
 * 患者画面の CSS の約束（読みやすさ）。jsdom は CSS を当てないので、規則の中身を検査する。
 */
import { beforeAll, describe, expect, it } from "vitest";

interface Fs {
  readFileSync(path: URL, encoding: "utf8"): string;
}

let css = "";

beforeAll(async () => {
  // vitest は CSS の import を（?raw でも）空にするので、node の fs で直接読む。
  // tsconfig の types に node が無いため、型は必要な分だけ書く
  const fs = (await import(/* @vite-ignore */ `node:${"fs"}`)) as Fs;
  css = fs.readFileSync(new URL("./patient.css", import.meta.url), "utf8");
});

/** selector の規則の本文（最初の1つ）。無ければ空文字。 */
function ruleOf(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`(?:^|\\n|,)\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(
    css,
  );
  return match?.[1] ?? "";
}

/** selector を含む規則（「a, b { }」のように並べたものも）の本文（最初の1つ）。 */
function groupRuleOf(selector: string): string {
  const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const match of code.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const selectors = (match[1] ?? "").split(",").map((x) => x.trim());
    if (selectors.includes(selector)) {
      return match[2] ?? "";
    }
  }
  return "";
}

/** :root 相当（.patient-app）の CSS 変数の値（#rrggbb）。 */
function varOf(name: string): string {
  const match = new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, "i").exec(css);
  if (!match?.[1]) {
    throw new Error(`${name} is missing`);
  }
  return match[1];
}

function rgbOf(hex: string): [number, number, number] {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return [r!, g!, b!];
}

/** WCAG のコントラスト比。 */
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

function remOf(body: string, property: string): number {
  const match = new RegExp(`${property}:\\s*([\\d.]+)rem`).exec(body);
  return match ? Number(match[1]) : NaN;
}

describe("patient.css", () => {
  it("自由記載の表示は長い英数字でも折り返す（改行は保つ）", () => {
    const body = ruleOf(".patient-app .p-entry-free-text");
    expect(body).toMatch(/overflow-wrap:\s*anywhere/);
    expect(body).toMatch(/white-space:\s*pre-wrap/);
  });

  it("h2 は本文（20px）より大きい", () => {
    expect(
      remOf(ruleOf(".patient-app h2"), "font-size"),
    ).toBeGreaterThanOrEqual(1.4);
  });

  it("PC-1: 架空の注記の枠は本文と同じ左右の余白を持つ", () => {
    const body = ruleOf(".patient-footer");
    expect(body).toMatch(/max-width:\s*560px/);
    expect(body).toMatch(/margin:\s*0 auto/);
    expect(body).toMatch(/padding:\s*0 16px/);
  });

  it("PC-2: 下のタブは画面の下に固定し、safe-area を足す。文字に下線を付けない", () => {
    const nav = ruleOf(".patient-app .p-nav");
    expect(nav).toMatch(/position:\s*fixed/);
    expect(nav).toMatch(/bottom:\s*0/);
    expect(nav).toMatch(/env\(safe-area-inset-bottom/);
    expect(ruleOf(".patient-app .p-nav a")).toMatch(/text-decoration:\s*none/);
    expect(ruleOf('.patient-app .p-nav a[aria-current="page"]')).toMatch(
      /background:/,
    );
  });

  it("PC-2: タブのある画面は、最後がタブに隠れないよう下をあける", () => {
    const body = ruleOf(".patient-app--with-nav");
    expect(body).toMatch(/padding-bottom:\s*calc\(var\(--p-nav-h\)/);
    expect(body).toMatch(/env\(safe-area-inset-bottom/);
  });

  it("選んだボタンはどの答えでも同じ青（答えごとの見た目はやめた）", () => {
    expect(css).not.toMatch(/\.p-choice--/);
    expect(css).not.toMatch(/--p-hard:/);
    const pressed = ruleOf('.patient-app button[aria-pressed="true"]');
    expect(pressed).toMatch(/background:\s*var\(--p-primary\)/);
    expect(pressed).toMatch(/color:\s*var\(--p-primary-text\)/);
    expect(pressed).toMatch(/border-width:\s*4px/);
    expect(
      ruleOf('.patient-app .p-choice[aria-pressed="true"]::before'),
    ).toMatch(/content:/);
  });

  it("何も選んでいない質問のボタンは薄い橙の地と濃い橙の枠（押せない時は灰のまま）", () => {
    const body = ruleOf(
      ".patient-app .p-choices--unanswered > .p-choice:not(:disabled)",
    );
    expect(body).toMatch(/background:\s*var\(--p-choice-prompt\)/);
    expect(body).toMatch(/border-color:\s*var\(--p-choice-prompt-border\)/);
    expect(body).not.toMatch(/color:\s*var\(--p-primary/);
    const fill = varOf("--p-choice-prompt");
    const border = varOf("--p-choice-prompt-border");
    // 橙: 赤 > 緑 > 青
    for (const hex of [fill, border]) {
      const [r, g, b] = rgbOf(hex);
      expect(r).toBeGreaterThan(g);
      expect(g).toBeGreaterThan(b);
    }
    expect(contrast(varOf("--p-text"), fill)).toBeGreaterThanOrEqual(4.5);
    // 枠は白い画面・代理入力の紫の画面・自分の地のどれに対しても 3:1 以上（WCAG 1.4.11）
    for (const around of ["--p-bg", "--p-proxy-bg", "--p-choice-prompt"]) {
      expect(contrast(border, varOf(around))).toBeGreaterThanOrEqual(3);
    }
    // 押せない時は灰のまま（:not(:disabled) の時だけ橙）
    expect(ruleOf(".patient-app button:disabled")).toMatch(
      /background:\s*var\(--p-surface\)/,
    );
  });

  it("P2-2: 押せないボタンは点線にしない（focus の輪と紛らわしい）", () => {
    expect(ruleOf(".patient-app button:disabled")).not.toMatch(/dashed/);
    expect(ruleOf(".patient-app :focus-visible")).toMatch(/outline:/);
  });

  it("P2-6: 「つらくて書けない」は紺の系統（紫を使わない）", () => {
    expect(css).not.toMatch(/#4a2373/i);
    const color = /--p-too-sick:\s*#([0-9a-f]{6})/i.exec(css)?.[1] ?? "";
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(color.slice(i, i + 2), 16));
    // 紺: 青が一番強く、赤は弱い
    expect(b!).toBeGreaterThan(r!);
    expect(b!).toBeGreaterThan(g!);
    expect(r!).toBeLessThan(0x20);
  });

  it("「つらくて書けない」は淡い紺の地＋紺の文字（4.5:1 以上）、確認中は濃い紺", () => {
    const body = ruleOf(".patient-app .p-button--too-sick");
    expect(body).toMatch(/color:\s*var\(--p-too-sick\)/);
    expect(body).toMatch(/background:\s*var\(--p-too-sick-bg\)/);
    expect(body).toMatch(/border:\s*3px solid var\(--p-too-sick\)/);
    expect(
      contrast(varOf("--p-too-sick"), varOf("--p-too-sick-bg")),
    ).toBeGreaterThanOrEqual(4.5);
    const open = ruleOf(
      '.patient-app .p-button--too-sick[aria-expanded="true"]',
    );
    expect(open).toMatch(/background:\s*var\(--p-too-sick\)/);
    expect(open).toMatch(/color:\s*#ffffff/);
  });

  it("自動で記録する「はい」は地が左から満ちる。動きを減らす設定では出さない", () => {
    const fill = ruleOf(".patient-app .p-countdown-fill");
    expect(fill).toMatch(/clip-path:\s*inset\(0 100% 0 0\)/);
    expect(fill).toMatch(/animation-name:\s*p-countdown-fill/);
    expect(css).toMatch(/@keyframes p-countdown-fill/);
    const reduced =
      /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.patient-app \.p-countdown-fill\s*\{([^}]*)\}/.exec(
        css,
      )?.[1] ?? "";
    expect(reduced).toMatch(/display:\s*none/);
    expect(reduced).toMatch(/animation:\s*none/);
    expect(
      contrast(varOf("--p-primary"), varOf("--p-too-sick-bg")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("代理入力中は画面全体と下のタブの地が薄い紫、チェック欄は濃い紫の太枠", () => {
    const page = groupRuleOf(".patient-app:has(.p-toggle--on)");
    expect(page).toMatch(/background:\s*var\(--p-proxy-bg\)/);
    expect(groupRuleOf(".patient-app:has(.p-toggle--on) .p-nav")).toMatch(
      /background:\s*var\(--p-proxy-bg\)/,
    );
    expect(ruleOf(".patient-app .p-toggle--on")).toMatch(
      /border:\s*4px solid var\(--p-proxy-border\)/,
    );
    const purple = varOf("--p-proxy-bg");
    const border = varOf("--p-proxy-border");
    expect(purple).not.toBe(varOf("--p-notice-bg"));
    // 紫: 青 > 赤 > 緑（未入力の橙・お知らせの黄とは別の色）
    for (const hex of [purple, border]) {
      const [r, g, b] = rgbOf(hex);
      expect(b).toBeGreaterThan(r);
      expect(r).toBeGreaterThan(g);
    }
    // 紫の画面の上でも、文字（黒・灰・赤・青）は 4.5:1 以上
    for (const text of ["--p-text", "--p-muted", "--p-error", "--p-primary"]) {
      expect(contrast(varOf(text), purple)).toBeGreaterThanOrEqual(4.5);
    }
    // 枠: チェック欄の紫・未入力の橙・白いボタンの枠は紫の画面に対して 3:1 以上
    for (const edge of [
      "--p-proxy-border",
      "--p-choice-prompt-border",
      "--p-border",
    ]) {
      expect(contrast(varOf(edge), purple)).toBeGreaterThanOrEqual(3);
    }
    expect(contrast(border, varOf("--p-bg"))).toBeGreaterThanOrEqual(3);
  });

  it("今日の記録の見出しの右の日付は、見出しより小さい灰色で、途中で折らない", () => {
    const date = ruleOf(".patient-app .p-title-date");
    expect(date).toMatch(/font-size:\s*18px/);
    expect(date).toMatch(/color:\s*var\(--p-muted\)/);
    expect(date).toMatch(/white-space:\s*nowrap/);
    expect(date).toMatch(/display:\s*inline-block/);
    // 見出しは 1.5rem（24px）。日付は 18px
    expect(remOf(ruleOf(".patient-app h1"), "font-size")).toBeGreaterThan(
      18 / 16,
    );
  });

  it("体温の欄はラベル・入力欄・単位を1行に並べ、入力欄は短く文字は大きい", () => {
    const row = ruleOf(".patient-app .p-temperature");
    expect(row).toMatch(/display:\s*flex/);
    expect(row).toMatch(/flex-wrap:\s*nowrap/);
    const input = ruleOf(".patient-app .p-temperature input");
    expect(input).toMatch(/width:\s*calc\(5ch/);
    expect(remOf(input, "font-size")).toBeGreaterThanOrEqual(1.5);
  });

  it("回答の表: 3列の幅をそろえ、選んだ欄は青地の太字、行の間に細い線", () => {
    expect(ruleOf(".patient-app .p-answers")).toMatch(/table-layout:\s*fixed/);
    expect(ruleOf(".patient-app .p-answers-col")).toMatch(/width:\s*\d+px/);
    const chosen = ruleOf(".patient-app .p-answer-cell--chosen strong");
    expect(chosen).toMatch(/font-weight:\s*700/);
    expect(chosen).toMatch(/background:\s*var\(--p-primary\)/);
    expect(chosen).toMatch(/border:/);
    expect(groupRuleOf(".patient-app .p-answers td")).toMatch(
      /border-bottom:\s*1px solid/,
    );
  });

  it("記録した内容の見出しは小さめの灰色", () => {
    const title = ruleOf(".patient-app .p-saved-title");
    expect(title).toMatch(/font-size:\s*18px/);
    expect(title).toMatch(/color:\s*var\(--p-muted\)/);
  });

  it("「つらくて書けない」と代理のトグルの間をあける", () => {
    const body = ruleOf(".patient-app .p-too-sick");
    const margin = /margin-top:\s*(\d+)px/.exec(body);
    expect(Number(margin?.[1] ?? 0)).toBeGreaterThanOrEqual(24);
  });

  describe("これまでの記録の一行の要約（タグ）", () => {
    it("タグは折り返して並び、1つのタグも横にはみ出さない", () => {
      const tags = ruleOf(".patient-app .p-tags");
      expect(tags).toMatch(/display:\s*flex/);
      expect(tags).toMatch(/flex-wrap:\s*wrap/);
      expect(tags).toMatch(/gap:/);
      const tag = ruleOf(".patient-app .p-tag");
      expect(tag).toMatch(/max-width:\s*100%/);
      expect(tag).toMatch(/overflow-wrap:\s*anywhere/);
      expect(tag).toMatch(/border-radius:\s*\d+px/);
      expect(tag).not.toMatch(/white-space:\s*nowrap/);
    });

    it("「ある」は淡い青の地＋紺の文字＋紺の細い枠（表の青と同じ）", () => {
      const body = ruleOf(".patient-app .p-tag--present");
      expect(body).toMatch(/color:\s*var\(--p-primary\)/);
      expect(body).toMatch(/background:\s*var\(--p-tag-present-bg\)/);
      expect(body).toMatch(/border-color:\s*var\(--p-primary\)/);
      const fill = varOf("--p-tag-present-bg");
      const [r, , b] = rgbOf(fill);
      expect(b).toBeGreaterThan(r);
      expect(contrast(varOf("--p-primary"), fill)).toBeGreaterThanOrEqual(4.5);
      // 一覧の1件の地（--p-surface）に対して枠が 3:1 以上
      expect(
        contrast(varOf("--p-primary"), varOf("--p-surface")),
      ).toBeGreaterThanOrEqual(3);
    });

    it("「つらい」は濃い紺の地＋白の文字（表の選んだ欄と同じ青）", () => {
      const body = ruleOf(".patient-app .p-tag--hard");
      expect(body).toMatch(/color:\s*var\(--p-primary-text\)/);
      expect(body).toMatch(/background:\s*var\(--p-primary\)/);
      expect(body).toMatch(/border-color:\s*var\(--p-primary\)/);
      expect(
        contrast(varOf("--p-primary-text"), varOf("--p-primary")),
      ).toBeGreaterThanOrEqual(4.5);
      expect(ruleOf(".patient-app .p-tag-mark")).toMatch(/font-weight:/);
    });

    it("体温・書いたこと・代理などは中立の見た目（白い地＋黒の文字＋灰の枠）", () => {
      const body = ruleOf(".patient-app .p-tag--neutral");
      expect(body).toMatch(/color:\s*var\(--p-text\)/);
      expect(body).toMatch(/background:\s*var\(--p-bg\)/);
      expect(body).toMatch(/border-color:\s*var\(--p-tag-neutral-border\)/);
      expect(body).toMatch(/font-weight:\s*400/);
      const border = varOf("--p-tag-neutral-border");
      const [r, g, b] = rgbOf(border);
      expect(r).toBe(g);
      expect(g).toBe(b);
      for (const around of ["--p-surface", "--p-bg"]) {
        expect(contrast(border, varOf(around))).toBeGreaterThanOrEqual(3);
      }
    });
  });
});
