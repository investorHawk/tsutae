/**
 * 医師 API の 2xx 応答の実行時検査（docs/architecture.md §9 W2b の決定）。
 * 形が契約（§8）と違えば ApiError(200, "invalid_response") にする。
 * {ok:false} を成功として扱わない（ログアウト・承認の誤認を防ぐ）。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch } from "../test/fetchMock";
import {
  approveSkillChange,
  checkDoctorSession,
  createPatient,
  createSkillChange,
  getPipelineEvents,
  listCourses,
  listPatients,
  listSkillChanges,
  listSkills,
  listUnprocessed,
  listVisits,
  login,
  logout,
  markPrinted,
  regenerateVisit,
  rejectSkillChange,
  saveCourse,
} from "./doctor";
import { ApiError, INVALID_RESPONSE } from "./http";

afterEach(() => {
  vi.unstubAllGlobals();
});

const COURSE = {
  patient_id: "P-DEMO0001",
  course_no: 2,
  infusion_date: "2026-10-13",
  planned_date: "2026-10-11",
  next_visit: null,
  note: null,
};

async function expectInvalid(body: unknown, call: () => Promise<unknown>) {
  mockFetch(() => jsonResponse(body));
  const err = await call().then(
    () => "resolved",
    (e: unknown) => e,
  );
  expect(err).toBeInstanceOf(ApiError);
  expect((err as ApiError).status).toBe(200);
  expect((err as ApiError).code).toBe(INVALID_RESPONSE);
}

const OK_BODIES_INVALID: Array<[string, unknown]> = [
  ["ok が false", { ok: false }],
  ["本文が空", {}],
  ["ok が文字列", { ok: "true" }],
  ["本文が null", null],
  ["本文が配列", [{ ok: true }]],
];

describe("{ok} の応答の検査", () => {
  it.each(OK_BODIES_INVALID)("login: %s は invalid_response", async (_l, b) => {
    await expectInvalid(b, () => login("demo-pass"));
  });

  it.each(OK_BODIES_INVALID)(
    "logout: %s は invalid_response",
    async (_l, b) => {
      await expectInvalid(b, () => logout());
    },
  );

  it.each(OK_BODIES_INVALID)(
    "markPrinted: %s は invalid_response",
    async (_l, b) => {
      await expectInvalid(b, () => markPrinted(12));
    },
  );

  it.each(OK_BODIES_INVALID)(
    "regenerateVisit: %s は invalid_response",
    async (_l, b) => {
      await expectInvalid(b, () => regenerateVisit(14));
    },
  );

  it.each(OK_BODIES_INVALID)(
    "approveSkillChange: %s は invalid_response",
    async (_l, b) => {
      await expectInvalid(b, () => approveSkillChange(3));
    },
  );

  it.each(OK_BODIES_INVALID)(
    "rejectSkillChange: %s は invalid_response",
    async (_l, b) => {
      await expectInvalid(b, () => rejectSkillChange(3));
    },
  );

  it.each([
    ["new_version が文字列", { ok: true, new_version: "2" }],
    ["new_version が 0", { ok: true, new_version: 0 }],
    ["new_version が小数", { ok: true, new_version: 2.5 }],
    ["new_version が null", { ok: true, new_version: null }],
    ["new_version が無い", { ok: true }],
  ])("approveSkillChange: %s は invalid_response", async (_l, b) => {
    await expectInvalid(b, () => approveSkillChange(3));
  });

  it("approveSkillChange: new_version は必須（W3 後の決定）で、あれば通す", async () => {
    mockFetch(() => jsonResponse({ ok: true, new_version: 2 }));
    await expect(approveSkillChange(3)).resolves.toEqual({
      ok: true,
      new_version: 2,
    });
  });

  it("rejectSkillChange: {ok: true} だけで通す（new_version は無い）", async () => {
    mockFetch(() => jsonResponse({ ok: true }));
    await expect(rejectSkillChange(3)).resolves.toEqual({ ok: true });
  });
});

describe("saveCourse の応答の検査", () => {
  const saved = (patch: Record<string, unknown>) => ({
    ...COURSE,
    id: 2,
    ...patch,
  });

  it.each([
    ["本文が空", {}],
    ["{ok:false}", { ok: false }],
    ["patient_id が無い", saved({ patient_id: undefined })],
    ["course_no が無い", saved({ course_no: undefined })],
    ["course_no が 0", saved({ course_no: 0 })],
    ["course_no が小数", saved({ course_no: 1.5 })],
    ["infusion_date が無い", saved({ infusion_date: undefined })],
    ["infusion_date が日付でない", saved({ infusion_date: "10/13" })],
    ["planned_date が日付でない", saved({ planned_date: "x" })],
    ["next_visit が数", saved({ next_visit: 1 })],
    ["note が数", saved({ note: 1 })],
    ["note が201字", saved({ note: "\u{1F600}".repeat(201) })],
    ["id が文字列", saved({ id: "2" })],
    ["送った患者と違う", saved({ patient_id: "P-OTHER001" })],
    ["送ったコース番号と違う", saved({ course_no: 3 })],
  ])("%s は invalid_response", async (_l, b) => {
    await expectInvalid(b, () => saveCourse(COURSE));
  });

  it("note が200字（絵文字）は通す", async () => {
    const body = saved({ note: "\u{1F600}".repeat(200) });
    mockFetch(() => jsonResponse(body));
    await expect(saveCourse(COURSE)).resolves.toEqual(body);
  });
});

describe("一覧・作成の応答の検査", () => {
  it.each<[string, unknown, () => Promise<unknown>]>([
    ["listPatients", {}, () => listPatients()],
    ["listPatients 要素", { patients: [{ id: 1 }] }, () => listPatients()],
    ["createPatient", { ok: true }, () => createPatient("FOLFOX")],
    ["listCourses", { courses: null }, () => listCourses("P-DEMO0001")],
    [
      "listCourses 要素",
      { courses: [{ ...COURSE, course_no: "2" }] },
      () => listCourses("P-DEMO0001"),
    ],
    ["listVisits", {}, () => listVisits()],
    ["listUnprocessed", {}, () => listUnprocessed(12)],
    ["getPipelineEvents", { events: [] }, () => getPipelineEvents(12)],
    ["listSkills", {}, () => listSkills()],
    [
      "listSkills 要素",
      { skills: [{ name: "x" }], invalid: [] },
      () => listSkills(),
    ],
    ["listSkills invalid が無い", { skills: [] }, () => listSkills()],
    [
      "listSkills invalid の要素",
      { skills: [], invalid: [{ name: "regimen-x", code: "format" }] },
      () => listSkills(),
    ],
    ["createSkillChange", { id: 3 }, () => createSkillChange("a", "b")],
    ["listSkillChanges", {}, () => listSkillChanges()],
  ])("%s: 壊れた本文は invalid_response", async (_l, b, call) => {
    await expectInvalid(b, call);
  });
});

describe("checkDoctorSession の壊れた 2xx", () => {
  it.each([
    ["本文が空", {}],
    ["{ok:false}", { ok: false }],
    ["skills が null", { skills: null }],
  ])(
    "%s はログイン済みと判定しない（invalid_response を投げる）",
    async (_l, b) => {
      await expectInvalid(b, () => checkDoctorSession());
    },
  );
});
