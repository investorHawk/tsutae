// @vitest-environment node
/**
 * アーキテクチャテスト: 患者画面の文字列は usePatientStrings().t(key) からだけ出す
 * （docs/architecture.md §9、spec 3.1・12節）。src/pages/patient と src/components/patient の
 * .ts / .tsx（テストと testing/ を除く）を構文木で検査する。許すのは t(...) のキー・
 * API の値（question.text 等の式）・数字と記号だけ。規則は src/test/patientTextLint.ts。
 * 患者画面の .tsx のテストと testing/ の .tsx には日本語が無いこと（期待値は s(key) から引く）。
 */
import { describe, expect, it } from "vitest";
import {
  findHardcodedText,
  findNonAsciiText,
} from "../../test/patientTextLint";

const sources = import.meta.glob<string>(
  [
    "../../pages/patient/**/*.{ts,tsx}",
    "./**/*.{ts,tsx}",
    "!**/*.test.{ts,tsx}",
    "!**/testing/**",
  ],
  { query: "?raw", import: "default", eager: true },
);

const testSources = import.meta.glob<string>(
  ["../../pages/patient/**/*.tsx", "./**/*.tsx"],
  { query: "?raw", import: "default", eager: true },
);

const testOnly = Object.entries(testSources).filter(
  ([file]) => file.includes(".test.") || file.includes("/testing/"),
);

describe("患者画面のテスト（.tsx）に直書きの日本語が無い", () => {
  it("検査対象に5画面のテストがある", () => {
    const files = testOnly.map(([file]) => file);
    for (const page of ["Register", "Today", "History", "Visit", "Settings"]) {
      expect(files).toContain(`../../pages/patient/${page}.test.tsx`);
    }
  });

  it.each(testOnly)("%s", (file, source) => {
    expect(findNonAsciiText(source, file)).toEqual([]);
  });

  it("日本語だけを拾い、英字は拾わない", () => {
    expect(findNonAsciiText('<p>today page</p>; const a = "x y z";')).toEqual(
      [],
    );
    expect(findNonAsciiText('<p>今日</p>; const a = "なし";')).toHaveLength(2);
  });
});

describe("患者画面（pages/patient・components/patient）に直書きの文字列が無い", () => {
  it("検査対象に5画面と部品と .ts の補助がある", () => {
    const files = Object.keys(sources);
    for (const page of ["Register", "Today", "History", "Visit", "Settings"]) {
      expect(files.some((f) => f.endsWith(`/pages/patient/${page}.tsx`))).toBe(
        true,
      );
    }
    for (const helper of [
      "history.ts",
      "reception.ts",
      "entryForm.ts",
      "patientApi.ts",
      "pushStatus.ts",
    ]) {
      expect(files).toContain(`./${helper}`);
    }
    expect(files.some((f) => f.includes(".test."))).toBe(false);
    expect(files.some((f) => f.includes("/testing/"))).toBe(false);
  });

  it.each(Object.entries(sources))("%s", (file, source) => {
    expect(findHardcodedText(source, file)).toEqual([]);
  });
});
