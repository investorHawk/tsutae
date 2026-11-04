import { describe, expect, it } from "vitest";
import { answerText, questionLabel } from "./answerLabels";

describe("answerText", () => {
  it.each([
    [
      { question_key: "diarrhea", value: "hard", temperature: null },
      "下痢 つらい",
    ],
    [
      { question_key: "numbness", value: "none", temperature: null },
      "しびれ なし",
    ],
    [
      { question_key: "stomatitis", value: "present", temperature: null },
      "口内炎 ある",
    ],
    [
      { question_key: "fever", value: "measured", temperature: 38 },
      "体温 38.0℃",
    ],
    [
      { question_key: "fever", value: "not_measured", temperature: null },
      "体温 測っていない",
    ],
  ] as const)("%o → %s", (answer, text) => {
    expect(answerText(answer)).toBe(text);
  });

  it("知らない質問は key をそのまま", () => {
    expect(questionLabel("taste")).toBe("taste");
  });
});
