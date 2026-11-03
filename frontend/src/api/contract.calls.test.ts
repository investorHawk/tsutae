/**
 * 契約テスト（呼び出し）: 実際の FastAPI の応答（src/test/fixtures/api/*.json。
 * scripts/dump_api_fixtures.py が書く）を、API の関数にそのまま流す。
 * - 送る経路・メソッド・本文が fixture と同じ
 * - 成功の本文は検査を通って、そのまま返る
 * - 失敗は ApiError(status, {"error"} の code) になる
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFixture, fixtureNames, type ApiFixture } from "../test/apiFixtures";
import { callOf, jsonResponse, mockFetch } from "../test/fetchMock";
import { validatePatientStrings } from "../strings/PatientStrings";
import {
  approveSkillChange,
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
  rejectSkillChange,
  saveCourse,
} from "./doctor";
import { ApiError } from "./http";
import {
  createEntry,
  getPatientStrings,
  getQuestions,
  listEntries,
  registerPatient,
  submitVisit,
} from "./patient";
import type { Course, EntryCreate, Regimen } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
});

type Call = (f: ApiFixture) => Promise<unknown>;

function req(f: ApiFixture): Record<string, unknown> {
  return (f.request ?? {}) as Record<string, unknown>;
}

/** 経路の中の仮名ID（P-XXXXXXXX）。 */
function pidIn(f: ApiFixture): string {
  const found = /\/(P-[A-Z0-9]{8})(?:\/|$)/.exec(f.path);
  if (!found) {
    throw new Error(`経路に仮名IDが無い: ${f.path}`);
  }
  return found[1];
}

/** 経路の中の数の id。 */
function idIn(f: ApiFixture): number {
  const found = /\/(\d+)(?:\/|$)/.exec(f.path);
  if (!found) {
    throw new Error(`経路に id が無い: ${f.path}`);
  }
  return Number(found[1]);
}

const register: Call = (f) => registerPatient(String(req(f).pid));
const questions: Call = (f) => getQuestions(pidIn(f));
const addEntry: Call = (f) => createEntry(pidIn(f), f.request as EntryCreate);
const entries: Call = (f) => listEntries(pidIn(f));
const visit: Call = (f) => submitVisit(String(req(f).reception_no));
const doctorLogin: Call = (f) => login(String(req(f).password));
const courses: Call = (f) => listCourses(pidIn(f));
const course: Call = (f) => saveCourse(f.request as Course);
const visits: Call = () => listVisits();
const unprocessed: Call = (f) => listUnprocessed(idIn(f));
const events: Call = (f) => getPipelineEvents(idIn(f));
const printed: Call = (f) => markPrinted(idIn(f));
const skills: Call = () => listSkills();
const change: Call = (f) =>
  createSkillChange(String(req(f).skill_name), String(req(f).request_text));
const approve: Call = (f) => approveSkillChange(idIn(f));
const reject: Call = (f) => rejectSkillChange(idIn(f));

/** fixture の名前 → それを受け取る API の関数。全ての fixture に要る。 */
const CALLS: Readonly<Record<string, Call>> = {
  patient_register: register,
  patient_register_unknown: register,
  patient_strings: () => getPatientStrings(),
  patient_questions: questions,
  patient_questions_forbidden: questions,
  patient_entry_create: addEntry,
  patient_entry_create_invalid: addEntry,
  patient_entries: entries,
  patient_entries_not_logged_in: entries,
  visit,
  visit_invalid: visit,
  visit_no_course: visit,
  doctor_login: doctorLogin,
  doctor_login_rejected: doctorLogin,
  doctor_logout: () => logout(),
  doctor_patients: () => listPatients(),
  doctor_patient_create: (f) => createPatient(req(f).regimen as Regimen),
  doctor_courses: courses,
  doctor_courses_unknown_patient: courses,
  doctor_course_save: course,
  doctor_course_save_invalid: course,
  doctor_visits: visits,
  doctor_visits_after_printed: visits,
  doctor_visits_not_logged_in: visits,
  doctor_unprocessed: unprocessed,
  doctor_unprocessed_not_found: unprocessed,
  doctor_pipeline_events: events,
  doctor_pipeline_events_generating: events,
  doctor_pipeline_events_printed: events,
  doctor_pipeline_events_not_found: events,
  doctor_printed: printed,
  doctor_printed_not_found: printed,
  doctor_skills: skills,
  doctor_skills_invalid: skills,
  doctor_skill_change_create: change,
  doctor_skill_change_create_failed: change,
  doctor_skill_change_create_invalid_name: change,
  doctor_skill_changes: () => listSkillChanges(),
  doctor_skill_change_approve: approve,
  doctor_skill_change_approve_busy: approve,
  doctor_skill_change_approve_not_pending: approve,
  doctor_skill_change_reject: reject,
  doctor_skill_change_reject_busy: reject,
};

const NAMES = fixtureNames();

describe("fixture の一覧", () => {
  it("fixture が読める（dump_api_fixtures.py を流してある）", () => {
    expect(NAMES.length).toBeGreaterThan(30);
  });

  it("全ての fixture に API の関数がある（足したら CALLS にも足す）", () => {
    expect(NAMES.filter((name) => !(name in CALLS))).toEqual([]);
  });

  it("CALLS の名前は全て fixture にある", () => {
    expect(Object.keys(CALLS).filter((name) => !NAMES.includes(name))).toEqual(
      [],
    );
  });
});

describe.each(NAMES)("fixture %s", (name) => {
  const fixture = apiFixture(name);
  const run = () => (CALLS[name] ?? (() => Promise.reject()))(fixture);

  it("経路・メソッド・本文が fixture と同じ", async () => {
    const mock = mockFetch(() => jsonResponse(fixture.body, fixture.status));
    await run().catch(() => undefined);
    const sent = callOf(mock);
    expect(sent.method).toBe(fixture.method);
    expect(sent.url).toBe(fixture.path);
    expect(sent.body ?? null).toEqual(fixture.request);
  });

  if (fixture.status < 400) {
    it("成功の本文は検査を通り、そのまま返る", async () => {
      mockFetch(() => jsonResponse(fixture.body, fixture.status));
      await expect(run()).resolves.toEqual(fixture.body);
    });
  } else {
    it("失敗は ApiError(status, code) になる", async () => {
      mockFetch(() => jsonResponse(fixture.body, fixture.status));
      const err = await run().then(
        () => "resolved",
        (e: unknown) => e,
      );
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(fixture.status);
      expect((err as ApiError).code).toBe(
        (fixture.body as { error: string }).error,
      );
    });
  }
});

describe("患者の定型文", () => {
  it("GET strings の本文は validatePatientStrings を通る（同梱のキーが全てある）", () => {
    expect(validatePatientStrings(apiFixture("patient_strings").body)).not.toBe(
      null,
    );
  });
});
