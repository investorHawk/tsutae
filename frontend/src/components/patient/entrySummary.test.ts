import { describe, expect, it } from "vitest";
import { ENTRIES, QUESTIONS } from "../../pages/patient/testing/fixtures";
import { summarizeEntry, summarySourceOf } from "./entrySummary";

describe("summarizeEntry", () => {
  it("つらくて書けない: それだけ", () => {
    expect(
      summarizeEntry({ tooSick: true, answers: [], freeText: null }),
    ).toEqual([{ kind: "too_sick" }]);
  });

  it("ある・つらい・測った体温を記録の順に、なし・測っていないは出さない", () => {
    expect(
      summarizeEntry({
        tooSick: false,
        answers: [
          { questionKey: "numbness", value: "hard", questionText: "q1" },
          { questionKey: "diarrhea", value: "present", questionText: "q2" },
          { questionKey: "stomatitis", value: "none", questionText: "q3" },
          {
            questionKey: "fever",
            value: "measured",
            temperature: 37.8,
            questionText: "q5",
          },
        ],
        freeText: null,
      }),
    ).toEqual([
      {
        kind: "answer",
        questionKey: "numbness",
        value: "hard",
        questionText: "q1",
      },
      {
        kind: "answer",
        questionKey: "diarrhea",
        value: "present",
        questionText: "q2",
      },
      {
        kind: "temperature",
        questionKey: "fever",
        temperature: 37.8,
        questionText: "q5",
      },
    ]);
  });

  it("答えが全て なし・測っていない: all_none", () => {
    expect(
      summarizeEntry({
        tooSick: false,
        answers: [
          { questionKey: "diarrhea", value: "none", questionText: null },
          { questionKey: "fever", value: "not_measured", questionText: null },
        ],
        freeText: null,
      }),
    ).toEqual([{ kind: "all_none" }]);
  });

  it("自由記載があれば最後に free_text（中身は出さない）", () => {
    expect(
      summarizeEntry({ tooSick: false, answers: [], freeText: "abc" }),
    ).toEqual([{ kind: "free_text" }]);
    expect(
      summarizeEntry({
        tooSick: false,
        answers: [
          { questionKey: "diarrhea", value: "none", questionText: null },
        ],
        freeText: "abc",
      }),
    ).toEqual([{ kind: "all_none" }, { kind: "free_text" }]);
  });

  it("空白だけの自由記載は無いのと同じ", () => {
    expect(
      summarizeEntry({ tooSick: false, answers: [], freeText: "  " }),
    ).toEqual([]);
  });

  it("measured でも体温が数でなければ出さない", () => {
    expect(
      summarizeEntry({
        tooSick: false,
        answers: [
          {
            questionKey: "fever",
            value: "measured",
            temperature: null,
            questionText: null,
          },
        ],
        freeText: null,
      }),
    ).toEqual([{ kind: "all_none" }]);
  });
});

describe("summarySourceOf", () => {
  it("GET entries の記録から作る（question_text を使う）", () => {
    expect(summarySourceOf(ENTRIES[1]!)).toEqual({
      tooSick: false,
      answers: [
        {
          questionKey: "diarrhea",
          value: "present",
          temperature: null,
          questionText: ENTRIES[1]!.answers[0]!.question_text,
        },
        {
          questionKey: "fever",
          value: "measured",
          temperature: 37.9,
          questionText: ENTRIES[1]!.answers[1]!.question_text,
        },
      ],
      freeText: ENTRIES[1]!.free_text,
    });
    expect(summarySourceOf(ENTRIES[0]!).tooSick).toBe(true);
  });

  it("送った EntryCreate と質問集から作る（質問文は質問集の文）", () => {
    const source = summarySourceOf(
      {
        by_proxy: false,
        answers: [
          { question_key: "fever", value: "measured", temperature: 38.2 },
          { question_key: "unknown", value: "present" },
        ],
        free_text: "x",
      },
      QUESTIONS,
    );
    expect(source).toEqual({
      tooSick: false,
      answers: [
        {
          questionKey: "fever",
          value: "measured",
          temperature: 38.2,
          questionText: QUESTIONS[4]!.text,
        },
        {
          questionKey: "unknown",
          value: "present",
          temperature: null,
          questionText: null,
        },
      ],
      freeText: "x",
    });
    expect(
      summarySourceOf({ too_sick: true, by_proxy: false }, QUESTIONS),
    ).toEqual({
      tooSick: true,
      answers: [],
      freeText: null,
    });
  });
});
