import { describe, expect, it } from "vitest";
import { BUNDLED_STRINGS } from "../../strings/bundledStrings";
import { QUESTION_ORDER, questionLabel, valueLabel } from "./answerLabels";

describe("questionLabel", () => {
  it("短い症状名は患者画面の symptom.<key> と同じ語", () => {
    for (const key of QUESTION_ORDER) {
      expect(questionLabel(key)).toBe(BUNDLED_STRINGS[`symptom.${key}`]);
    }
  });

  it("患者画面の symptom.<key> を全て持つ", () => {
    const patientKeys = Object.keys(BUNDLED_STRINGS)
      .filter((k) => k.startsWith("symptom."))
      .map((k) => k.slice("symptom.".length));
    expect([...QUESTION_ORDER].sort()).toEqual(patientKeys.sort());
  });

  it("知らない質問は key をそのまま", () => {
    expect(questionLabel("taste")).toBe("taste");
  });
});

describe("valueLabel", () => {
  it.each([
    ["none", "なし"],
    ["present", "ある"],
    ["hard", "つらい"],
    ["not_measured", "測っていない"],
    ["measured", "測った"],
  ] as const)("%s → %s", (value, text) => {
    expect(valueLabel(value)).toBe(text);
  });
});
