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

  it("P2-1: 「つらい」を選んだ時は「ある」より濃い色で、色以外（内側の白い輪）でも分かる", () => {
    const present = groupRuleOf(
      '.patient-app .p-choice--present[aria-pressed="true"]',
    );
    const hard = groupRuleOf(
      '.patient-app .p-choice--hard[aria-pressed="true"]',
    );
    expect(present).toMatch(/background:\s*var\(--p-primary\)/);
    expect(hard).toMatch(/background:\s*var\(--p-hard\)/);
    expect(hard).toMatch(/box-shadow:\s*inset/);
    expect(css).toMatch(/--p-hard:\s*#[0-9a-f]{6}/);
  });

  it("P2-1: 「なし」も選んだことが分かる（薄い塗りと太枠）", () => {
    const none = groupRuleOf(
      '.patient-app .p-choice--none[aria-pressed="true"]',
    );
    expect(none).toMatch(/background:\s*var\(--p-choice-light\)/);
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

  it("P3-2: 記録の答えは太字", () => {
    expect(ruleOf(".patient-app .p-entry dd")).toMatch(/font-weight:\s*700/);
  });

  it("「つらくて書けない」と代理のトグルの間をあける", () => {
    const body = ruleOf(".patient-app .p-too-sick");
    const margin = /margin-top:\s*(\d+)px/.exec(body);
    expect(Number(margin?.[1] ?? 0)).toBeGreaterThanOrEqual(24);
  });
});
