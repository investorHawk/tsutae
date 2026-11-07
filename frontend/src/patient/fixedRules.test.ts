import { describe, expect, it } from "vitest";
import type { ClosedAnswer, FixedRule } from "../api/types";
import { apiFixture } from "../test/apiFixtures";
import cases from "../test/fixtures/fixed_rule_cases.json";
import { noticesFor } from "./fixedRules";

const FEVER_KEY = "fixed_rule.fever_38";

/** 実際の GET questions の規則（backend のテストと同じ FOLFOX の規則）。 */
const RULES = (
  apiFixture("patient_questions").body as { fixed_rules: FixedRule[] }
).fixed_rules;

function fever(temperature: number): { answers: ClosedAnswer[] } {
  return {
    answers: [{ question_key: "fever", value: "measured", temperature }],
  };
}

interface SharedCase {
  name: string;
  too_sick: boolean;
  answers: ClosedAnswer[];
  notices: string[];
}

describe("backend の fixed_rules.py と同じ表", () => {
  it("表は空でなく、38.0 の境目を含む", () => {
    expect(cases.length).toBeGreaterThan(0);
    expect(RULES.map((r) => r.threshold_celsius)).toEqual([38]);
  });

  it.each(cases as SharedCase[])("$name", ({ too_sick, answers, notices }) => {
    expect(noticesFor({ too_sick, answers }, RULES)).toEqual(notices);
  });
});

describe("noticesFor", () => {
  it("答えが無い記録は案内しない（自由記載は読まない）", () => {
    expect(noticesFor({}, RULES)).toEqual([]);
    expect(noticesFor({ answers: [] }, RULES)).toEqual([]);
  });

  it("規則が無ければ案内しない", () => {
    expect(noticesFor(fever(39), [])).toEqual([]);
  });

  it("規則の順に並べ、同じキーは1回だけ", () => {
    const rules: FixedRule[] = [
      {
        question_key: "fever",
        threshold_celsius: 38,
        patient_string_key: FEVER_KEY,
      },
      {
        question_key: "fever",
        threshold_celsius: 37,
        patient_string_key: "fixed_rule.other",
      },
      {
        question_key: "fever",
        threshold_celsius: 38,
        patient_string_key: FEVER_KEY,
      },
    ];
    expect(noticesFor(fever(38.4), rules)).toEqual([
      FEVER_KEY,
      "fixed_rule.other",
    ]);
    expect(noticesFor(fever(37.5), rules)).toEqual(["fixed_rule.other"]);
  });

  it("引数を書き換えない", () => {
    const entry = fever(38);
    const rules = structuredClone(RULES);
    const before = structuredClone({ entry, rules });
    noticesFor(entry, rules);
    expect({ entry, rules }).toEqual(before);
  });
});
