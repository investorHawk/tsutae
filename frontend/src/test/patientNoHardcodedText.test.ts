// @vitest-environment node
/**
 * 患者画面の文字列は usePatientStrings().t(key) からだけ出す（docs/architecture.md §9）。
 * ここでは検査器（patientTextLint）自身と、ページ以外の患者向けのファイル
 * （レイアウト・定型文の読み込み・仮名ID）を検査する。ページと部品は
 * components/patient/noHardcodedText.test.ts。
 */
import { describe, expect, it } from "vitest";
import { findHardcodedText } from "./patientTextLint";

const sources = import.meta.glob<string>(
  [
    "../layouts/PatientLayout.tsx",
    "../strings/**/*.{ts,tsx}",
    "../patient/**/*.{ts,tsx}",
    "!**/*.test.{ts,tsx}",
  ],
  { query: "?raw", import: "default", eager: true },
);

function texts(source: string): string[] {
  return findHardcodedText(source).map((v) => v.text);
}

describe("患者画面の周り（レイアウト・定型文・仮名ID）に直書きの文字列が無い", () => {
  it("検査対象のファイルがある", () => {
    const files = Object.keys(sources);
    expect(files.some((f) => f.endsWith("/PatientLayout.tsx"))).toBe(true);
    expect(files.some((f) => f.endsWith("/PatientStrings.tsx"))).toBe(true);
    expect(files.some((f) => f.endsWith("/pid.ts"))).toBe(true);
    expect(files.some((f) => f.includes(".test."))).toBe(false);
  });

  it.each(Object.entries(sources))("%s", (file, source) => {
    expect(findHardcodedText(source, file)).toEqual([]);
  });
});

describe("検査器（findHardcodedText）", () => {
  it.each([
    ["JSX の英字", "<p>AI advice</p>"],
    ["JSX の英単語1つ", "<p>Error</p>"],
    ["JSX の日本語", "<h1>今日の記録</h1>"],
    ["JSX の全角英数", "<p>ＡＢＣ</p>"],
    ["JSX の式の文字列", '<p>{"Error"}</p>'],
    ["JSX の条件式の文字列", '<p>{ok ? "Yes" : t("a.b")}</p>'],
    ["JSX の && の文字列", '<p>{ok && "Saved"}</p>'],
    ["JSX のテンプレート", "<p>{`${n} items`}</p>"],
    ["JSX の配列の文字列", '<p>{["AI", "advice"]}</p>'],
    ["読み上げの属性", '<button aria-label="Close" />'],
    ["placeholder", '<input placeholder="Type here" />'],
    ["title の式", '<p title={"Help"} />'],
    ["変数の英文", 'const label = "AI advice";'],
    ["変数の日本語", 'const label = "なし";'],
    ["テンプレートの日本語", "const at = `${h}時`;"],
    ["テンプレートの英文", "const at = `${h} hours ago`;"],
    ["関数が返す英文", 'function f() { return "Please retry"; }'],
    ["Error の日本語", 'throw new Error("形式が正しくない");'],
  ])("%s を見つける", (_label, sample) => {
    expect(findHardcodedText(sample)).not.toEqual([]);
  });

  it.each([
    ["定型文", '<h1>{t("today.title")}</h1>'],
    ["キーのテンプレート", "<dd>{t(`answer.${answer.value}`)}</dd>"],
    ["質問文", "<p>{question.text}</p>"],
    ["数字と記号", "<p>{a} / {b} 36.8 - :</p>"],
    ["空白", '<p>{" "}{x}</p>'],
    [
      "class・id・型",
      '<input className="p-a p-b" id={`${id}-error`} type="text" />',
    ],
    ["キーの文字列", 'const KEY = "error.not_registered";'],
    ["英語の console", 'console.warn("patient string not found", key);'],
    ["英語の Error", 'throw new Error("pid is not valid");'],
    ["import", 'import x from "./some file";'],
    [
      "コメント",
      "/** 説明 */\n// 行のコメント\nconst a = 1; {/* JSX のコメント */}",
    ],
  ])("%s は通す", (_label, sample) => {
    expect(texts(sample)).toEqual([]);
  });

  it.each([
    ["日本語の文字列リテラル", 'const label = "なし";', "non-ascii"],
    ["JSX のテキストの英字", "<p>Advice</p>", "jsx-text"],
  ])("契約の2規則（§9 W2b）: %s", (_label, sample, rule) => {
    expect(findHardcodedText(sample).map((v) => v.rule)).toEqual([rule]);
  });

  it("行番号と規則を返す", () => {
    const found = findHardcodedText('const a = 1;\nconst b = "AI advice";');
    expect(found).toEqual([
      { line: 2, rule: "ascii-prose", text: '"AI advice"' },
    ]);
  });
});

/**
 * 既知の限界（docs/architecture.md §9 W2b の決定「変数経由の英字は検査の外」、frontend/README.md）。
 * 検査が強くなったらこのテストは落ちる。そのときは「見つける」側へ移す。
 */
describe("検査の外（既知の限界）", () => {
  it("1語の英字を変数に入れてから描くものは見逃す", () => {
    expect(
      findHardcodedText('const label = "Advice";\n<p>{label}</p>'),
    ).toEqual([]);
  });

  it("2語以上の英文は、変数に入れても ascii-prose で見つける", () => {
    expect(
      findHardcodedText('const label = "AI advice";\n<p>{label}</p>').map(
        (v) => v.rule,
      ),
    ).toEqual(["ascii-prose"]);
  });
});
