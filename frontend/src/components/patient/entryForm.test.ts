import { describe, expect, it } from "vitest";
import { QUESTIONS } from "../../pages/patient/testing/fixtures";
import type { Question } from "../../api/types";
import {
  EMPTY_FORM,
  FREE_TEXT_MAX,
  buildEntry,
  invalidTemperatureKeys,
  setTemperatureText,
  hasInput,
  parseTemperature,
  setAnswer,
  temperatureErrors,
  temperatureProblem,
  unansweredCount,
  type EntryFormState,
} from "./entryForm";

describe("parseTemperature", () => {
  it.each([
    ["36.8", 36.8],
    ["37", 37],
    ["30", 30],
    ["45", 45],
    ["45.0", 45],
    [" 38.2 ", 38.2],
    ["３６．８", 36.8],
    // schemas.py は 30.0〜45.0 の任意の有限 float を受ける（小数の桁数の制限は無い）
    ["37.25", 37.25],
    ["36.85", 36.85],
    ["44.999", 44.999],
  ])("%s は %s", (text, expected) => {
    expect(parseTemperature(text)).toBe(expected);
  });

  it.each([
    "",
    "   ",
    "29.9",
    "45.1",
    "45.01",
    "368",
    "3",
    "abc",
    "36,8",
    "36.",
    ".5",
    "-36",
    "1e1",
  ])("%j は不正（null）", (text) => {
    expect(parseTemperature(text)).toBeNull();
  });
});

function form(patch: Partial<EntryFormState>): EntryFormState {
  return { ...EMPTY_FORM, ...patch };
}

describe("buildEntry", () => {
  it("答えた質問だけを質問集の順に送る", () => {
    const result = buildEntry(
      QUESTIONS,
      form({ answers: { stomatitis: "hard", numbness: "none" } }),
    );
    expect(result).toEqual({
      ok: true,
      entry: {
        by_proxy: false,
        answers: [
          { question_key: "numbness", value: "none" },
          { question_key: "stomatitis", value: "hard" },
        ],
        free_text: null,
      },
    });
  });

  it("体温: 測ったら temperature を付ける", () => {
    const result = buildEntry(
      QUESTIONS,
      form({
        answers: { fever: "measured" },
        temperatureTexts: { fever: "38.2" },
      }),
    );
    expect(result).toEqual({
      ok: true,
      entry: {
        by_proxy: false,
        answers: [
          { question_key: "fever", value: "measured", temperature: 38.2 },
        ],
        free_text: null,
      },
    });
  });

  it("体温: 測っていないなら temperature を付けない（入力欄の値は捨てる）", () => {
    const result = buildEntry(
      QUESTIONS,
      form({
        answers: { fever: "not_measured" },
        temperatureTexts: { fever: "38.2" },
      }),
    );
    expect(result).toEqual({
      ok: true,
      entry: {
        by_proxy: false,
        answers: [{ question_key: "fever", value: "not_measured" }],
        free_text: null,
      },
    });
  });

  it("体温: 測ったのに数値が不正なら送らない", () => {
    expect(
      buildEntry(
        QUESTIONS,
        form({
          answers: { fever: "measured" },
          temperatureTexts: { fever: "50" },
        }),
      ),
    ).toEqual({ ok: false, reason: "temperature_invalid" });
  });

  it("自由記載は前後の空白を落とす。代理入力を付ける", () => {
    const result = buildEntry(
      QUESTIONS,
      form({ freeText: "  おなかがゆるい\n", byProxy: true }),
    );
    expect(result).toEqual({
      ok: true,
      entry: { by_proxy: true, answers: [], free_text: "おなかがゆるい" },
    });
  });

  it("自由記載は 2000 字まで（code point で数える。絵文字2000個は UTF-16 で4000単位）", () => {
    const text = "\u{1F600}".repeat(FREE_TEXT_MAX);
    expect(buildEntry(QUESTIONS, form({ freeText: ` ${text}\n` }))).toEqual({
      ok: true,
      entry: { by_proxy: false, answers: [], free_text: text },
    });
  });

  it("自由記載が 2001 字なら送らない（黙って切らない）", () => {
    const text = "\u{1F600}".repeat(FREE_TEXT_MAX + 1);
    expect(buildEntry(QUESTIONS, form({ freeText: text }))).toEqual({
      ok: false,
      reason: "free_text_too_long",
    });
  });

  it("何も無ければ送らない（代理入力だけ・空白だけも空）", () => {
    expect(buildEntry(QUESTIONS, EMPTY_FORM)).toEqual({
      ok: false,
      reason: "empty",
    });
    expect(
      buildEntry(QUESTIONS, form({ byProxy: true, freeText: " \n " })),
    ).toEqual({ ok: false, reason: "empty" });
  });

  it("質問集に無いキー・答えの型が合わない値は送らない", () => {
    const result = buildEntry(
      QUESTIONS,
      form({
        answers: {
          unknown_key: "present",
          fever: "hard",
          diarrhea: "measured",
        },
        freeText: "x",
      }),
    );
    expect(result).toEqual({
      ok: true,
      entry: { by_proxy: false, answers: [], free_text: "x" },
    });
  });

  it("引数を書き換えない", () => {
    const state = form({ answers: { diarrhea: "present" } });
    const snapshot = JSON.stringify(state);
    buildEntry(QUESTIONS, state);
    expect(JSON.stringify(state)).toBe(snapshot);
  });
});

/** 体温の質問が2つある質問集（D4 で足せる。schemas.py は禁じていない）。 */
const TWO_FEVERS: readonly Question[] = [
  ...QUESTIONS,
  { key: "fever_evening", text: "evening", answer_type: "temperature" },
];

describe("体温の質問が2つ以上", () => {
  it("それぞれの入力欄の値を、その質問の回答に付ける", () => {
    const result = buildEntry(
      TWO_FEVERS,
      form({
        answers: { fever: "measured", fever_evening: "measured" },
        temperatureTexts: { fever: "38.2", fever_evening: "36.5" },
      }),
    );
    expect(result).toEqual({
      ok: true,
      entry: {
        by_proxy: false,
        answers: [
          { question_key: "fever", value: "measured", temperature: 38.2 },
          {
            question_key: "fever_evening",
            value: "measured",
            temperature: 36.5,
          },
        ],
        free_text: null,
      },
    });
  });

  it("片方だけ入れたら、もう片方が不正で送らない（値を使い回さない）", () => {
    const state = form({
      answers: { fever: "measured", fever_evening: "measured" },
      temperatureTexts: { fever: "38.2" },
    });
    expect(buildEntry(TWO_FEVERS, state)).toEqual({
      ok: false,
      reason: "temperature_invalid",
    });
    expect([...invalidTemperatureKeys(TWO_FEVERS, state)]).toEqual([
      "fever_evening",
    ]);
  });

  it("測っていない質問の入力欄は検査しない", () => {
    const state = form({
      answers: { fever: "measured", fever_evening: "not_measured" },
      temperatureTexts: { fever: "38.2", fever_evening: "x" },
    });
    expect([...invalidTemperatureKeys(TWO_FEVERS, state)]).toEqual([]);
    expect(buildEntry(TWO_FEVERS, state).ok).toBe(true);
  });

  it("setTemperatureText はその質問の欄だけを変えた新しい状態を返す", () => {
    const first = setTemperatureText(EMPTY_FORM, "fever", "38.2");
    const second = setTemperatureText(first, "fever_evening", "36.5");
    expect(second.temperatureTexts).toEqual({
      fever: "38.2",
      fever_evening: "36.5",
    });
    expect(first.temperatureTexts).toEqual({ fever: "38.2" });
    expect(EMPTY_FORM.temperatureTexts).toEqual({});
  });
});

describe("setAnswer", () => {
  it("新しい状態を返し、同じ値を押し直すと取り消す", () => {
    const first = setAnswer(EMPTY_FORM, "diarrhea", "present");
    expect(first.answers).toEqual({ diarrhea: "present" });
    expect(EMPTY_FORM.answers).toEqual({});
    const changed = setAnswer(first, "diarrhea", "hard");
    expect(changed.answers).toEqual({ diarrhea: "hard" });
    expect(first.answers).toEqual({ diarrhea: "present" });
    const cleared = setAnswer(changed, "diarrhea", "hard");
    expect(cleared.answers).toEqual({});
  });
});

describe("hasInput / unansweredCount", () => {
  it("回答か自由記載があれば入力あり", () => {
    expect(hasInput(EMPTY_FORM)).toBe(false);
    expect(hasInput(form({ byProxy: true }))).toBe(false);
    expect(hasInput(form({ freeText: "  " }))).toBe(false);
    expect(hasInput(form({ freeText: "a" }))).toBe(true);
    expect(hasInput(form({ answers: { diarrhea: "none" } }))).toBe(true);
  });

  it("押していない質問の数", () => {
    expect(unansweredCount(QUESTIONS, EMPTY_FORM)).toBe(5);
    expect(
      unansweredCount(
        QUESTIONS,
        form({ answers: { diarrhea: "none", fever: "not_measured" } }),
      ),
    ).toBe(3);
  });
});

describe("temperatureProblem", () => {
  it.each([
    ["36.8", null],
    ["\uff13\uff16\uff0e\uff18", null],
    ["30", null],
    ["45", null],
    ["", "invalid"],
    ["   ", "invalid"],
    ["abc", "invalid"],
    ["36.8.1", "invalid"],
    ["-36", "invalid"],
    ["1e2", "invalid"],
    ["368", "out_of_range"],
    ["50", "out_of_range"],
    ["45.1", "out_of_range"],
    ["29.9", "out_of_range"],
    ["3.68", "out_of_range"],
  ])("%j は %s", (text, expected) => {
    expect(temperatureProblem(text)).toBe(expected);
  });
});

describe("temperatureErrors", () => {
  it("測った質問ごとに、数字でない・範囲外を分けて返す（質問集の順）", () => {
    const state = form({
      answers: { fever: "measured", fever_evening: "measured" },
      temperatureTexts: { fever: "368", fever_evening: "x" },
    });
    expect([...temperatureErrors(TWO_FEVERS, state)]).toEqual([
      ["fever", "out_of_range"],
      ["fever_evening", "invalid"],
    ]);
  });

  it("正しい値・測っていない質問は含めない", () => {
    const state = form({
      answers: { fever: "measured", fever_evening: "not_measured" },
      temperatureTexts: { fever: "36.8", fever_evening: "x" },
    });
    expect(temperatureErrors(TWO_FEVERS, state).size).toBe(0);
  });
});
