/**
 * 患者 API の 2xx 応答の実行時検査（docs/architecture.md §9 W2b の決定）。
 * 形が契約（§8）と違えば ApiError(200, "invalid_response") にし、画面は error.generic を出す。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch } from "../test/fetchMock";
import { ApiError, INVALID_RESPONSE } from "./http";
import {
  createEntry,
  getQuestions,
  listEntries,
  registerPatient,
  submitVisit,
} from "./patient";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PID = "P-DEMO0001";

const QUESTION = {
  key: "diarrhea",
  text: "下痢はありましたか",
  answer_type: "three_level",
};

const ENTRY = {
  id: 1,
  recorded_at: "2026-11-01T20:00:00+09:00",
  record_date: "2026-11-01",
  kind: "answers",
  by_proxy: false,
  skill_version: "regimen-folfox@1",
  answers: [
    {
      question_key: "diarrhea",
      value: "present",
      temperature: null,
      question_text: "下痢はありましたか",
    },
  ],
  free_text: null,
};

async function failureOf(call: () => Promise<unknown>): Promise<unknown> {
  return call().then(
    () => "resolved",
    (err: unknown) => err,
  );
}

async function expectInvalid(body: unknown, call: () => Promise<unknown>) {
  mockFetch(() => jsonResponse(body));
  const err = await failureOf(call);
  expect(err).toBeInstanceOf(ApiError);
  expect((err as ApiError).status).toBe(200);
  expect((err as ApiError).code).toBe(INVALID_RESPONSE);
}

describe("getQuestions の応答の検査", () => {
  it.each([
    ["questions が無い", { skill_version: "regimen-folfox@1" }],
    ["questions が null", { skill_version: "x", questions: null }],
    ["本文が配列", [QUESTION]],
    ["本文が null", null],
    ["要素が文字列", { skill_version: "x", questions: ["diarrhea"] }],
    [
      "key が無い",
      { skill_version: "x", questions: [{ ...QUESTION, key: 1 }] },
    ],
    [
      "text が null",
      { skill_version: "x", questions: [{ ...QUESTION, text: null }] },
    ],
    [
      "answer_type が未知",
      {
        skill_version: "x",
        questions: [{ ...QUESTION, answer_type: "scale" }],
      },
    ],
    ["skill_version が無い", { questions: [QUESTION] }],
    ["skill_version が null", { skill_version: null, questions: [QUESTION] }],
    ["skill_version が数", { skill_version: 1, questions: [QUESTION] }],
    [
      "質問の key が重複",
      { skill_version: "x", questions: [QUESTION, { ...QUESTION }] },
    ],
  ])("%s は invalid_response", async (_label, body) => {
    await expectInvalid(body, () => getQuestions(PID));
  });

  it("正しい形はそのまま返す", async () => {
    const body = { skill_version: "regimen-folfox@1", questions: [QUESTION] };
    mockFetch(() => jsonResponse(body));
    await expect(getQuestions(PID)).resolves.toEqual(body);
  });
});

describe("createEntry の応答の検査", () => {
  it.each([
    ["notices が無い", { entry_id: 1 }],
    ["notices が null", { entry_id: 1, notices: null }],
    ["notices に数", { entry_id: 1, notices: [38] }],
    ["notices が文字列", { entry_id: 1, notices: "fixed_rule.fever_38" }],
    ["entry_id が無い", { notices: [] }],
    ["本文が空", {}],
  ])("%s は invalid_response", async (_label, body) => {
    await expectInvalid(body, () => createEntry(PID, { too_sick: true }));
  });

  it("正しい形はそのまま返す", async () => {
    const body = { entry_id: 3, notices: ["fixed_rule.fever_38"] };
    mockFetch(() => jsonResponse(body));
    await expect(createEntry(PID, { too_sick: true })).resolves.toEqual(body);
  });
});

describe("listEntries の応答の検査", () => {
  const withEntry = (patch: Record<string, unknown>) => ({
    entries: [{ ...ENTRY, ...patch }],
  });
  const withAnswer = (patch: Record<string, unknown>) =>
    withEntry({ answers: [{ ...ENTRY.answers[0], ...patch }] });

  it.each([
    ["entries が無い", {}],
    ["entries が null", { entries: null }],
    ["要素が null", { entries: [null] }],
    ["answers が無い", withEntry({ answers: undefined })],
    ["answers が null", withEntry({ answers: null })],
    ["kind が未知", withEntry({ kind: "ai_summary" })],
    ["by_proxy が文字列", withEntry({ by_proxy: "no" })],
    ["free_text が数", withEntry({ free_text: 1 })],
    ["recorded_at が無い", withEntry({ recorded_at: undefined })],
    ["回答が文字列", withEntry({ answers: ["present"] })],
    ["回答の value が未知", withAnswer({ value: "very_hard" })],
    ["回答の question_key が無い", withAnswer({ question_key: undefined })],
    ["回答の temperature が文字列", withAnswer({ temperature: "38.2" })],
    ["回答の question_text が数", withAnswer({ question_text: 1 })],
    // 契約（§8）で列挙された項目は、nullable でも「存在して null」でなければならない
    ["skill_version が無い", withEntry({ skill_version: undefined })],
    ["skill_version が null", withEntry({ skill_version: null })],
    ["free_text が無い", withEntry({ free_text: undefined })],
    ["回答の question_text が無い", withAnswer({ question_text: undefined })],
    ["回答の temperature が無い", withAnswer({ temperature: undefined })],
    // ClosedAnswer: measured のときだけ temperature（30.0〜45.0）
    [
      "measured なのに temperature が null",
      withAnswer({ question_key: "fever", value: "measured" }),
    ],
    [
      "measured なのに temperature が無い",
      withAnswer({
        question_key: "fever",
        value: "measured",
        temperature: undefined,
      }),
    ],
    ["measured 以外に temperature", withAnswer({ temperature: 37.2 })],
    [
      "not_measured に temperature",
      withAnswer({
        question_key: "fever",
        value: "not_measured",
        temperature: 36.5,
      }),
    ],
    [
      "temperature が範囲外（29.9）",
      withAnswer({
        question_key: "fever",
        value: "measured",
        temperature: 29.9,
      }),
    ],
    [
      "temperature が範囲外（45.1）",
      withAnswer({
        question_key: "fever",
        value: "measured",
        temperature: 45.1,
      }),
    ],
    [
      "同じ記録に同じ question_key が2つ",
      withEntry({ answers: [ENTRY.answers[0], { ...ENTRY.answers[0] }] }),
    ],
  ])("%s は invalid_response", async (_label, body) => {
    await expectInvalid(body, () => listEntries(PID));
  });

  it("question_text が null の回答は通す（質問集に無い。画面は history.previous_question）", async () => {
    const body = withAnswer({ question_text: null });
    mockFetch(() => jsonResponse(body));
    await expect(listEntries(PID)).resolves.toEqual(body);
  });

  it.each([30, 37.25, 45])("measured で temperature %s は通す", async (t) => {
    const body = withAnswer({
      question_key: "fever",
      value: "measured",
      temperature: t,
    });
    mockFetch(() => jsonResponse(body));
    await expect(listEntries(PID)).resolves.toEqual(body);
  });
});

describe("登録・受診の応答の検査", () => {
  it.each([
    ["本文が空", {}],
    ["ok が false", { ok: false }],
    ["本文が null", null],
  ])("registerPatient: %s は invalid_response", async (_label, body) => {
    await expectInvalid(body, () => registerPatient(PID));
  });

  it.each([
    ["本文が空", {}],
    ["ok が無い", { message_key: "visit.done" }],
    ["message_key が数", { ok: true, message_key: 1 }],
  ])("submitVisit: %s は invalid_response", async (_label, body) => {
    await expectInvalid(body, () => submitVisit("A-023"));
  });
});
