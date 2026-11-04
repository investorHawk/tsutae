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

  it("「つらくて書けない」と代理のトグルの間をあける", () => {
    const body = ruleOf(".patient-app .p-too-sick");
    const margin = /margin-top:\s*(\d+)px/.exec(body);
    expect(Number(margin?.[1] ?? 0)).toBeGreaterThanOrEqual(24);
  });
});
