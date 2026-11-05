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
  addLibraryQuestion,
  approveSkillChange,
  checkMasks,
  createPatient,
  createSkillChange,
  getPipelineEvents,
  getSkill,
  hideLibraryQuestion,
  listCourses,
  listPatientEntries,
  listPatientVisits,
  listPatients,
  listQuestionLibrary,
  listRegimens,
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
  saveMasks,
} from "./doctor";
import { ApiError } from "./http";
import {
  createEntry,
  getPatientStrings,
  getQuestions,
  listEntries,
  registerPatient,
  submitVisit,
  undoEntry,
} from "./patient";
import {
  deletePushSubscription,
  getPushConfig,
  putPushSubscription,
  sendPushTest,
  type PushSubscriptionRequest,
} from "./patientPush";
import type {
  AddLibraryQuestionRequest,
  Course,
  EntryCreate,
  MaskCheckRequest,
  MaskSaveRequest,
  Regimen,
} from "./types";
import {
  adoptRegimenDraft,
  createRegimenDraft,
  discardRegimenDraft,
  getRegimenDraft,
  listRegimenDrafts,
  listRegimenDrugNames,
  patchRegimenFields,
  postRegimenTurn,
  previewRegimenDraft,
} from "./regimenDrafts";
import type {
  AdoptRegimenRequest,
  CreateRegimenDraftRequest,
  PatchRegimenFieldsRequest,
} from "./regimenTypes";

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
const undo: Call = (f) => undoEntry(pidIn(f), idIn(f));
const pushSubscribe: Call = (f) =>
  putPushSubscription(pidIn(f), f.request as PushSubscriptionRequest);
const pushUnsubscribe: Call = (f) =>
  deletePushSubscription(pidIn(f), String(req(f).endpoint));
const pushTest: Call = (f) => sendPushTest(pidIn(f), String(req(f).endpoint));
const visit: Call = (f) => submitVisit(String(req(f).reception_no));
const doctorLogin: Call = (f) => login(String(req(f).password));
const courses: Call = (f) => listCourses(pidIn(f));
const patientVisits: Call = (f) => listPatientVisits(pidIn(f));
const patientEntries: Call = (f) => listPatientEntries(pidIn(f));
const course: Call = (f) => saveCourse(f.request as Course);
const visits: Call = () => listVisits();
const unprocessed: Call = (f) => listUnprocessed(idIn(f));
const events: Call = (f) => getPipelineEvents(idIn(f));
const printed: Call = (f) => markPrinted(idIn(f));
const regenerate: Call = (f) => regenerateVisit(idIn(f));
const maskCheck: Call = (f) => {
  const body = f.request as MaskCheckRequest;
  return checkMasks(idIn(f), body.entry_id, body.spans);
};
const maskSave: Call = (f) =>
  saveMasks(idIn(f), (f.request as MaskSaveRequest).entries);
const skills: Call = () => listSkills();
/** 経路の最後の Skill 名（GET skills/{name}）。 */
const skill: Call = (f) => getSkill(f.path.replace(/^.*\//, ""));
const change: Call = (f) =>
  createSkillChange(String(req(f).skill_name), String(req(f).request_text));
const approve: Call = (f) => approveSkillChange(idIn(f));
const reject: Call = (f) => rejectSkillChange(idIn(f));
const addQuestion: Call = (f) =>
  addLibraryQuestion(f.request as AddLibraryQuestionRequest);
const draftCreate: Call = (f) =>
  createRegimenDraft(f.request as CreateRegimenDraftRequest);
const draftGet: Call = (f) => getRegimenDraft(idIn(f));
const draftFields: Call = (f) =>
  patchRegimenFields(idIn(f), f.request as PatchRegimenFieldsRequest);
const draftPreview: Call = (f) => previewRegimenDraft(idIn(f));
const draftAdopt: Call = (f) =>
  adoptRegimenDraft(idIn(f), f.request as AdoptRegimenRequest);
const draftDiscard: Call = (f) => discardRegimenDraft(idIn(f));
const draftTurn: Call = (f) => postRegimenTurn(idIn(f), String(req(f).text));
/** 経路の最後の質問 key（DELETE question-library/{key}）。 */
const hideQuestion: Call = (f) =>
  hideLibraryQuestion(f.path.replace(/^.*\//, ""));

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
  patient_entry_undo: undo,
  patient_entry_undo_not_found: undo,
  patient_entry_undo_not_undoable: undo,
  patient_push_config: () => getPushConfig(),
  patient_push_config_unavailable: () => getPushConfig(),
  patient_push_subscribe: pushSubscribe,
  patient_push_subscribe_gone: pushSubscribe,
  patient_push_subscribe_invalid: pushSubscribe,
  patient_push_subscribe_unavailable: pushSubscribe,
  patient_push_unsubscribe: pushUnsubscribe,
  patient_push_test: pushTest,
  patient_push_test_not_found: pushTest,
  patient_push_test_too_soon: pushTest,
  visit,
  visit_invalid: visit,
  visit_no_course: visit,
  doctor_login: doctorLogin,
  doctor_login_rejected: doctorLogin,
  doctor_logout: () => logout(),
  doctor_patients: () => listPatients(),
  doctor_patient_create: (f) => createPatient(req(f).regimen as Regimen),
  doctor_patient_create_unknown_regimen: (f) =>
    createPatient(req(f).regimen as Regimen),
  doctor_regimens: () => listRegimens(),
  doctor_courses: courses,
  doctor_courses_unknown_patient: courses,
  doctor_patient_visits: patientVisits,
  doctor_patient_visits_open: patientVisits,
  doctor_patient_visits_unknown_patient: patientVisits,
  doctor_patient_entries: patientEntries,
  doctor_patient_entries_unknown_patient: patientEntries,
  doctor_course_save: course,
  doctor_course_save_invalid: course,
  doctor_visits: visits,
  doctor_visits_after_printed: visits,
  doctor_visits_not_logged_in: visits,
  doctor_unprocessed: unprocessed,
  doctor_unprocessed_not_found: unprocessed,
  doctor_unprocessed_masked: unprocessed,
  doctor_masks_check: maskCheck,
  doctor_masks_check_clean: maskCheck,
  doctor_masks_check_invalid_spans: maskCheck,
  doctor_masks_check_unknown_entry: maskCheck,
  doctor_masks_save: maskSave,
  doctor_masks_save_closed: maskSave,
  doctor_pipeline_events: events,
  doctor_pipeline_events_generating: events,
  doctor_pipeline_events_printed: events,
  doctor_pipeline_events_not_found: events,
  doctor_printed: printed,
  doctor_printed_not_found: printed,
  doctor_regenerate: regenerate,
  doctor_regenerate_not_regenerable: regenerate,
  doctor_regenerate_not_found: regenerate,
  doctor_skills: skills,
  doctor_skills_invalid: skills,
  doctor_skill: skill,
  doctor_skill_unknown: skill,
  doctor_skill_change_create: change,
  doctor_skill_change_create_failed: change,
  doctor_skill_change_create_invalid_name: change,
  doctor_skill_change_create_regimen: change,
  doctor_skill_changes: () => listSkillChanges(),
  doctor_skill_change_approve: approve,
  doctor_skill_change_approve_busy: approve,
  doctor_skill_change_approve_not_pending: approve,
  doctor_skill_change_reject: reject,
  doctor_skill_change_reject_busy: reject,
  doctor_question_library: () => listQuestionLibrary(),
  doctor_question_library_add: addQuestion,
  doctor_question_library_add_taken: addQuestion,
  doctor_question_library_hide: hideQuestion,
  doctor_question_library_hide_seed: hideQuestion,
  doctor_regimen_drafts: () => listRegimenDrafts(),
  doctor_regimen_drug_names: () => listRegimenDrugNames(),
  doctor_regimen_draft: draftGet,
  doctor_regimen_draft_missing: draftGet,
  doctor_regimen_draft_create: draftCreate,
  doctor_regimen_draft_create_existing: draftCreate,
  doctor_regimen_draft_fields: draftFields,
  doctor_regimen_draft_fields_existing: draftFields,
  doctor_regimen_draft_fields_invalid: draftFields,
  doctor_regimen_draft_preview: draftPreview,
  doctor_regimen_draft_preview_diff: draftPreview,
  doctor_regimen_draft_adopt: draftAdopt,
  doctor_regimen_draft_adopt_unconfirmed: draftAdopt,
  doctor_regimen_draft_adopt_token_mismatch: draftAdopt,
  doctor_regimen_draft_discard: draftDiscard,
  doctor_regimen_draft_discard_closed: draftDiscard,
  doctor_regimen_draft_turn: draftTurn,
  doctor_regimen_draft_turn_failed: draftTurn,
  doctor_regimen_draft_turn_h1: draftTurn,
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
