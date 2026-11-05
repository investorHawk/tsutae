/**
 * 契約テスト（検査）: 実際の FastAPI の成功の本文（src/test/fixtures/api/*.json）を
 * 各 guard が受け入れ、壊した本文（項目の欠け・型違い・契約外の値）を拒むこと。
 * W3 後の決定: 印刷待ち一覧は generating・ready・failed だけで受付番号は必ずある、
 * GET skills は invalid を必ず持つ、approve の new_version は必須（reject は {ok:true}）。
 */
import { describe, expect, it } from "vitest";
import { apiFixture, fixtureBody, fixtureNames } from "../test/apiFixtures";
import { validatePatientStrings } from "../strings/PatientStrings";
import {
  isAdoptRegimenResponse,
  isCreateRegimenDraftResponse,
  isRegimenDraftResponse,
  isRegimenDraftsResponse,
  isRegimenPreviewResponse,
  isRegimenTurnResponse,
} from "./regimenGuards";
import {
  isAddLibraryQuestionResponse,
  isApproveResponse,
  isCoursesResponse,
  isCreatePatientResponse,
  isCreateSkillChangeResponse,
  isMaskCheckResponse,
  isMaskSaveResponse,
  isOkTrue as isDoctorOk,
  isPatientEntriesSummaryResponse,
  isPatientVisitsResponse,
  isPatientsResponse,
  isPipelineEventsResponse,
  isQuestionLibraryResponse,
  isRegimensResponse,
  isSavedCourse,
  isSkillChangesResponse,
  isSkillContentResponse,
  isSkillsResponse,
  isUnprocessedResponse,
  isVisitsResponse,
} from "./doctorGuards";
import {
  isCreateEntryResponse,
  isOkTrue as isPatientOk,
  isPatientEntriesResponse,
  isQuestionsResponse,
  isVisitResponse,
} from "./patientGuards";
import type { Course } from "./types";
import { type Item, isRecord } from "./validate";

type Guard = (body: Item) => boolean;

const savedCourse: Guard = (body) =>
  isSavedCourse(apiFixture("doctor_course_save").request as Course)(body);

/** 成功の fixture → その本文の guard。成功の fixture は全てここに要る。 */
const GUARDS: Readonly<Record<string, Guard>> = {
  patient_register: isPatientOk,
  patient_questions: isQuestionsResponse,
  patient_entry_create: isCreateEntryResponse,
  patient_entries: isPatientEntriesResponse,
  patient_entry_undo: isPatientOk,
  patient_strings: (body) => validatePatientStrings(body) !== null,
  visit: isVisitResponse,
  doctor_login: isDoctorOk,
  doctor_logout: isDoctorOk,
  doctor_patients: isPatientsResponse,
  doctor_patient_create: isCreatePatientResponse,
  doctor_regimens: isRegimensResponse,
  doctor_courses: isCoursesResponse,
  doctor_patient_visits: isPatientVisitsResponse,
  doctor_patient_visits_open: isPatientVisitsResponse,
  doctor_patient_entries: isPatientEntriesSummaryResponse,
  doctor_course_save: savedCourse,
  doctor_visits: isVisitsResponse,
  doctor_visits_after_printed: isVisitsResponse,
  doctor_unprocessed: isUnprocessedResponse,
  doctor_unprocessed_masked: isUnprocessedResponse,
  doctor_masks_check: isMaskCheckResponse,
  doctor_masks_check_clean: isMaskCheckResponse,
  doctor_masks_save: isMaskSaveResponse,
  doctor_pipeline_events: isPipelineEventsResponse,
  doctor_pipeline_events_generating: isPipelineEventsResponse,
  doctor_pipeline_events_printed: isPipelineEventsResponse,
  doctor_printed: isDoctorOk,
  doctor_regenerate: isDoctorOk,
  doctor_skills: isSkillsResponse,
  doctor_skills_invalid: isSkillsResponse,
  doctor_skill: isSkillContentResponse,
  doctor_skill_change_create: isCreateSkillChangeResponse,
  doctor_skill_change_create_failed: isCreateSkillChangeResponse,
  doctor_skill_changes: isSkillChangesResponse,
  doctor_skill_change_approve: isApproveResponse,
  doctor_skill_change_reject: isDoctorOk,
  doctor_question_library: isQuestionLibraryResponse,
  doctor_question_library_add: isAddLibraryQuestionResponse,
  doctor_question_library_hide: isDoctorOk,
  doctor_regimen_drafts: isRegimenDraftsResponse,
  doctor_regimen_draft: isRegimenDraftResponse,
  doctor_regimen_draft_create: isCreateRegimenDraftResponse,
  doctor_regimen_draft_create_existing: isCreateRegimenDraftResponse,
  doctor_regimen_draft_fields: isRegimenDraftResponse,
  doctor_regimen_draft_fields_existing: isRegimenDraftResponse,
  doctor_regimen_draft_preview: isRegimenPreviewResponse,
  doctor_regimen_draft_preview_diff: isRegimenPreviewResponse,
  doctor_regimen_draft_adopt: isAdoptRegimenResponse,
  doctor_regimen_draft_discard: isDoctorOk,
  doctor_regimen_draft_turn: isRegimenTurnResponse,
  doctor_regimen_draft_turn_failed: isRegimenTurnResponse,
};

function guardOf(name: string): Guard {
  const guard = GUARDS[name];
  if (!guard) {
    throw new Error(`guard が無い: ${name}`);
  }
  return guard;
}

/** guard に掛ける（本文がオブジェクトでなければ不合格）。 */
function passes(name: string, body: unknown): boolean {
  return isRecord(body) && guardOf(name)(body);
}

const SUCCESS = fixtureNames().filter((n) => apiFixture(n).status < 400);

describe("成功の fixture は guard を通る", () => {
  it("成功の fixture は全て GUARDS にある", () => {
    expect(SUCCESS.filter((name) => !(name in GUARDS))).toEqual([]);
    expect(Object.keys(GUARDS).filter((n) => !SUCCESS.includes(n))).toEqual([]);
  });

  it.each(SUCCESS)("%s", (name) => {
    expect(passes(name, fixtureBody(name))).toBe(true);
  });
});

// 壊す操作を短く書くため、ここだけ any を使う（本文は fixtureBody の深い写し）
type Mutate = (body: any) => void;

/** [fixture, 壊し方の説明, 壊す操作]。壊した本文は guard に拒まれる。 */
const BROKEN: Array<[string, string, Mutate]> = [
  // レジメンの一覧（T95）
  ["doctor_regimens", "regimens が無い", (b) => delete b.regimens],
  ["doctor_regimens", "識別名が小文字", (b) => (b.regimens[0].code = "folfox")],
  [
    "doctor_regimens",
    "Skill 名が識別名と合わない",
    (b) => (b.regimens[1].skill_name = "regimen-folfox"),
  ],
  ["doctor_regimens", "版が 0", (b) => (b.regimens[0].version = 0)],
  ["doctor_regimens", "表示名が無い", (b) => delete b.regimens[0].display_name],
  [
    "doctor_regimens",
    "識別名が重なる",
    (b) => b.regimens.push({ ...b.regimens[0] }),
  ],
  [
    "doctor_patients",
    "レジメンの識別名の書式が違う",
    (b) => (b.patients[0].regimen = "folfox"),
  ],
  [
    "doctor_patient_entries",
    "回答の短い名前が省略",
    (b) => delete b.entries[0].answers[0].question_label,
  ],
  [
    "doctor_patient_entries",
    "回答の短い名前が数",
    (b) => (b.entries[0].answers[0].question_label = 1),
  ],
  // D4 レジメンの下書き（v1.1）
  ["doctor_regimen_drafts", "未知の状態", (b) => (b.drafts[0].status = "x")],
  ["doctor_regimen_drafts", "version が 0", (b) => (b.drafts[0].version = 0)],
  [
    "doctor_regimen_drafts",
    "updated_at に時差が無い",
    (b) => (b.drafts[0].updated_at = "2026-11-09T10:00:00"),
  ],
  [
    "doctor_regimen_draft",
    "regimen が無い（null でなく省略）",
    (b) => delete b.draft.regimen,
  ],
  [
    "doctor_regimen_draft",
    "未知の出どころ",
    (b) => (b.draft.sources["basic.code"] = "ai"),
  ],
  [
    "doctor_regimen_draft",
    "未知の経路",
    (b) => (b.draft.form.drugs[0].route = "iv"),
  ],
  [
    "doctor_regimen_draft",
    "Day の範囲が数でない",
    (b) => (b.draft.form.drugs[0].days[0].start = "1"),
  ],
  [
    "doctor_regimen_draft",
    "描画用の文 prose が出ている",
    (b) => (b.draft.form.prose = {}),
  ],
  [
    "doctor_regimen_draft",
    "schedule_locked が無い",
    (b) => delete b.draft.schedule_locked,
  ],
  ["doctor_regimen_draft_create", "created が無い", (b) => delete b.created],
  [
    "doctor_regimen_draft_preview",
    "AI の値の出どころが doctor_edit",
    (b) => (b.ai_values[0].source = "doctor_edit"),
  ],
  [
    "doctor_regimen_draft_preview",
    "AI の値の出どころが doctor_text（一覧は標準の値だけ）",
    (b) => (b.ai_values[0].source = "doctor_text"),
  ],
  [
    "doctor_regimen_draft_preview",
    "検査の結果があるのに SKILL.md がある",
    (b) => (b.issues = [{ field_id: "notes", code: "x", message: "x" }]),
  ],
  [
    "doctor_regimen_draft_preview",
    "confirm_token の形が違う",
    (b) => (b.confirm_token = "abc"),
  ],
  [
    "doctor_regimen_draft_preview_diff",
    "SKILL.md の種類が未知",
    (b) => (b.skill_md.kind = "patch"),
  ],
  ["doctor_regimen_draft_adopt", "ok が false", (b) => (b.ok = false)],
  ["doctor_regimen_draft_adopt", "version が無い", (b) => delete b.version],
  // D4 レジメンの1往復（T94）
  [
    "doctor_regimen_draft_turn",
    "turn_error が無い（null でなく省略）",
    (b) => delete b.turn_error,
  ],
  ["doctor_regimen_draft_turn", "turn_error が数", (b) => (b.turn_error = 1)],
  [
    "doctor_regimen_draft_turn",
    "未知の role",
    (b) => (b.draft.chat[0].role = "patient"),
  ],
  [
    "doctor_regimen_draft_turn",
    "先生の文が無い",
    (b) => delete b.draft.chat[0].text,
  ],
  [
    "doctor_regimen_draft_turn",
    "会話の行の at に時差が無い",
    (b) => (b.draft.chat[0].at = "2026-11-09T10:00:00"),
  ],
  [
    "doctor_regimen_draft_turn",
    "変えた欄が配列でない",
    (b) => (b.draft.chat[1].changed = "basic.cycle_days"),
  ],
  [
    "doctor_regimen_draft_turn",
    "ask が無い（null でなく省略）",
    (b) => delete b.draft.chat[1].ask,
  ],
  [
    "doctor_regimen_draft_turn",
    "ask の選択肢が1つ",
    (b) => (b.draft.chat[1].ask.options = ["Day1"]),
  ],
  [
    "doctor_regimen_draft_turn",
    "reply_hidden が無い",
    (b) => delete b.draft.chat[1].reply_hidden,
  ],
  [
    "doctor_regimen_draft_turn_failed",
    "失敗の行に reason が無い",
    (b) => delete b.draft.chat[3].reason,
  ],
  [
    "doctor_regimen_draft_turn_failed",
    "generation が負",
    (b) => (b.draft.chat[3].generation = -1),
  ],
  // 質問の部品集（v1.1）
  [
    "doctor_question_library",
    "label が無い",
    (b) => delete b.questions[0].label,
  ],
  [
    "doctor_question_library",
    "未知の出どころ",
    (b) => (b.questions[0].origin = "ai"),
  ],
  [
    "doctor_question_library",
    "未知の回答の型",
    (b) => (b.questions[0].answer_type = "yes_no"),
  ],
  ["doctor_question_library", "questions が無い", (b) => delete b.questions],
  [
    "doctor_question_library_add",
    "question が null",
    (b) => (b.question = null),
  ],
  ["doctor_question_library_add", "text が数", (b) => (b.question.text = 1)],
  ["doctor_question_library_hide", "ok が false", (b) => (b.ok = false)],
  // 印刷待ち一覧（W3 後の決定）
  ["doctor_visits", "状態が printed", (b) => (b.visits[0].status = "printed")],
  ["doctor_visits", "未知の状態", (b) => (b.visits[0].status = "done")],
  [
    "doctor_visits",
    "受付番号が null",
    (b) => (b.visits[0].reception_no = null),
  ],
  ["doctor_visits", "受付番号が無い", (b) => delete b.visits[0].reception_no],
  ["doctor_visits", "fallback が数", (b) => (b.visits[0].fallback = 0)],
  [
    "doctor_visits",
    "未処理件数が無い",
    (b) => delete b.visits[0].unprocessed_count,
  ],
  ["doctor_visits", "visits が無い", (b) => delete b.visits],
  // Skill の中身（GET skills/{name}）
  ["doctor_skill", "text が無い", (b) => delete b.text],
  ["doctor_skill", "questions が配列でない", (b) => (b.questions = {})],
  [
    "doctor_skill",
    "質問の answer_type が知らない値",
    (b) => (b.questions[0].answer_type = "free"),
  ],
  ["doctor_skill", "version が文字列", (b) => (b.version = "1")],
  // Skill の一覧（invalid）
  ["doctor_skills", "invalid が無い", (b) => delete b.invalid],
  ["doctor_skills", "invalid が配列でない", (b) => (b.invalid = {})],
  [
    "doctor_skills",
    "skills の version が文字列",
    (b) => (b.skills[0].version = "1"),
  ],
  [
    "doctor_skills_invalid",
    "error_code が無い",
    (b) => delete b.invalid[0].error_code,
  ],
  [
    "doctor_skills_invalid",
    "required が文字列",
    (b) => (b.invalid[0].required = "no"),
  ],
  ["doctor_skills_invalid", "name が数", (b) => (b.invalid[0].name = 1)],
  // 承認・却下
  [
    "doctor_skill_change_approve",
    "new_version が無い",
    (b) => delete b.new_version,
  ],
  [
    "doctor_skill_change_approve",
    "new_version が null",
    (b) => (b.new_version = null),
  ],
  [
    "doctor_skill_change_approve",
    "new_version が 0",
    (b) => (b.new_version = 0),
  ],
  ["doctor_skill_change_approve", "ok が false", (b) => (b.ok = false)],
  ["doctor_skill_change_reject", "ok が false", (b) => (b.ok = false)],
  ["doctor_skill_change_reject", "ok が無い", (b) => delete b.ok],
  // Skill の書き換え
  ["doctor_skill_change_create", "status が未知", (b) => (b.status = "done")],
  ["doctor_skill_change_create", "id が文字列", (b) => (b.id = "1")],
  ["doctor_skill_change_create", "diff が数", (b) => (b.diff = 1)],
  [
    "doctor_skill_changes",
    "status が未知",
    (b) => (b.skill_changes[0].status = "x"),
  ],
  [
    "doctor_skill_changes",
    "base_version が無い",
    (b) => delete b.skill_changes[0].base_version,
  ],
  [
    "doctor_skill_changes",
    "created_at が無い",
    (b) => delete b.skill_changes[0].created_at,
  ],
  // D5・D6
  ["doctor_pipeline_events", "status が未知", (b) => (b.status = "running")],
  ["doctor_pipeline_events", "ts が無い", (b) => delete b.events[0].ts],
  [
    "doctor_pipeline_events",
    "duration_ms が文字列",
    (b) => (b.events[0].duration_ms = "1"),
  ],
  ["doctor_pipeline_events", "events が無い", (b) => delete b.events],
  ["doctor_unprocessed", "text が無い", (b) => delete b.entries[0].text],
  [
    "doctor_unprocessed",
    "entry_id が文字列",
    (b) => (b.entries[0].entry_id = "38"),
  ],
  ["doctor_unprocessed", "marks が無い", (b) => delete b.entries[0].marks],
  [
    "doctor_unprocessed",
    "印の終わりが文の外",
    (b) => (b.entries[0].marks = [{ start: 0, end: 999 }]),
  ],
  [
    "doctor_unprocessed",
    "印が空（start = end）",
    (b) => (b.entries[0].marks = [{ start: 2, end: 2 }]),
  ],
  [
    "doctor_unprocessed",
    "印が重なる",
    (b) =>
      (b.entries[0].marks = [
        { start: 0, end: 4 },
        { start: 3, end: 5 },
      ]),
  ],
  [
    "doctor_unprocessed",
    "印の start が負",
    (b) => (b.entries[0].marks = [{ start: -1, end: 4 }]),
  ],
  // 医師の伏せ字（D6 で伏せて変換し直す）
  [
    "doctor_unprocessed",
    "doctor_mask が無い",
    (b) => delete b.entries[0].doctor_mask,
  ],
  [
    "doctor_unprocessed_masked",
    "doctor_mask の区間が文の外",
    (b) => (b.entries[0].doctor_mask.spans = [{ start: 0, end: 999 }]),
  ],
  [
    "doctor_unprocessed_masked",
    "doctor_mask の confirmed_clear が無い",
    (b) => delete b.entries[0].doctor_mask.confirmed_clear,
  ],
  [
    "doctor_masks_check",
    "suspects の区間が文の外",
    (b) => (b.suspects[0].end = 999),
  ],
  [
    "doctor_masks_check",
    "suspects の rule が無い",
    (b) => delete b.suspects[0].rule,
  ],
  ["doctor_masks_check", "masked_text が無い", (b) => delete b.masked_text],
  ["doctor_masks_check", "reason が無い", (b) => delete b.reason],
  ["doctor_masks_check", "confirmable が文字列", (b) => (b.confirmable = "1")],
  ["doctor_masks_save", "ok が false", (b) => (b.ok = false)],
  ["doctor_masks_save", "sendable が負", (b) => (b.sendable = -1)],
  // 見出しの受診（医師画面の UX の見直し）
  ["doctor_unprocessed", "visit が無い", (b) => delete b.visit],
  [
    "doctor_unprocessed",
    "visit の仮名IDが無い",
    (b) => delete b.visit.patient_id,
  ],
  [
    "doctor_unprocessed",
    "visit の report_available が文字列",
    (b) => (b.visit.report_available = "yes"),
  ],
  ["doctor_unprocessed", "記録の Day が 0", (b) => (b.entries[0].day = 0)],
  [
    "doctor_unprocessed",
    "記録のコースが文字列",
    (b) => (b.entries[0].course_no = "3"),
  ],
  ["doctor_pipeline_events", "visit が無い", (b) => delete b.visit],
  [
    "doctor_pipeline_events_printed",
    "visit の受付番号が数",
    (b) => (b.visit.reception_no = 23),
  ],
  [
    "doctor_pipeline_events",
    "visit の状態が未知",
    (b) => (b.visit.status = "done"),
  ],
  ["doctor_patient_entries", "記録の Day が負", (b) => (b.entries[0].day = -1)],
  // 患者の画面の受診・記録（D2）
  [
    "doctor_patient_visits",
    "report_available が無い",
    (b) => delete b.visits[0].report_available,
  ],
  [
    "doctor_patient_visits",
    "受付番号が無い（null でなく省略）",
    (b) => delete b.visits[0].reception_no,
  ],
  [
    "doctor_patient_visits_open",
    "状態が未知",
    (b) => (b.visits[0].status = "done"),
  ],
  ["doctor_patient_entries", "total が無い", (b) => delete b.total],
  [
    "doctor_patient_entries",
    "has_free_text が無い",
    (b) => delete b.entries[0].has_free_text,
  ],
  [
    "doctor_patient_entries",
    "measured なのに体温が null",
    (b) => (b.entries[0].answers[0].temperature = null),
  ],
  [
    "doctor_patient_entries",
    "回答の値が未知",
    (b) => (b.entries[0].answers[1].value = "maybe"),
  ],
  // 患者・コース
  [
    "doctor_patients",
    "最後の記録日が無い（null でなく省略）",
    (b) => delete b.patients[0].last_record_date,
  ],
  [
    "doctor_patients",
    "今のコースが 0",
    (b) => (b.patients[0].current_course_no = 0),
  ],
  ["doctor_patients", "今の Day が 0", (b) => (b.patients[0].current_day = 0)],
  [
    "doctor_patients",
    "途切れが文字列",
    (b) => (b.patients[0].record_stale = "true"),
  ],
  [
    "doctor_patients",
    "記録からの日数が小数",
    (b) => (b.patients[0].days_since_last_record = 1.5),
  ],
  [
    "doctor_patients",
    "次回受診が無い（null でなく省略）",
    (b) => delete b.patients[0].next_visit,
  ],
  // v1.1: regimen は識別名の書式だけを見る（置かれているかは GET regimens）
  [
    "doctor_patients",
    "regimen が識別名の書式でない",
    (b) => (b.patients[0].regimen = "XELOX "),
  ],
  [
    "doctor_patients",
    "register_url が無い",
    (b) => delete b.patients[0].register_url,
  ],
  [
    "doctor_patient_create",
    "register_url が無い",
    (b) => delete b.register_url,
  ],
  [
    "doctor_courses",
    "実投与日の形が違う",
    (b) => (b.courses[0].infusion_date = "2026/09/27"),
  ],
  ["doctor_courses", "course_no が 0", (b) => (b.courses[0].course_no = 0)],
  ["doctor_course_save", "別のコース番号", (b) => (b.course_no = 9)],
  ["doctor_login", "ok が false", (b) => (b.ok = false)],
  ["doctor_printed", "ok が無い", (b) => delete b.ok],
  ["doctor_regenerate", "ok が false", (b) => (b.ok = false)],
  ["doctor_regenerate", "ok が無い", (b) => delete b.ok],
  // 患者 API
  ["patient_register", "ok が false", (b) => (b.ok = false)],
  [
    "patient_questions",
    "answer_type が未知",
    (b) => (b.questions[0].answer_type = "free"),
  ],
  [
    "patient_questions",
    "key が重複",
    (b) => (b.questions[1].key = b.questions[0].key),
  ],
  ["patient_questions", "skill_version が無い", (b) => delete b.skill_version],
  ["patient_questions", "today が無い", (b) => delete b.today],
  ["patient_entry_create", "notices に数", (b) => (b.notices = [1])],
  ["patient_entry_create", "entry_id が無い", (b) => delete b.entry_id],
  ["patient_entries", "kind が未知", (b) => (b.entries[0].kind = "other")],
  [
    "patient_entries",
    "question_text が無い",
    (b) => delete lastAnswer(b).question_text,
  ],
  [
    "patient_entries",
    "measured なのに体温が null",
    (b) => (lastEntry(b).answers[0].temperature = null),
  ],
  ["patient_entries", "free_text が無い", (b) => delete b.entries[0].free_text],
  ["patient_entries", "visits が無い", (b) => delete b.visits],
  ["patient_entries", "visits の要素が文字列", (b) => (b.visits = ["x"])],
  [
    "patient_entries",
    "visit_date が重複",
    (b) => (b.visits = [b.visits[0], { ...b.visits[0] }]),
  ],
  [
    "patient_entries",
    "visit_date が無い",
    (b) => delete b.visits[0].visit_date,
  ],
  [
    "patient_entries",
    "received_at が無い",
    (b) => delete b.visits[0].received_at,
  ],
  ["visit", "message_key が無い", (b) => delete b.message_key],
  ["patient_strings", "必須の定型文が無い", (b) => delete b["visit.done"]],
];

function lastEntry(b: any): any {
  return b.entries[b.entries.length - 1];
}

function lastAnswer(b: any): any {
  return lastEntry(b).answers[0];
}

describe("壊した fixture は guard に拒まれる", () => {
  it.each(BROKEN)("%s: %s", (name, _label, mutate) => {
    const body = fixtureBody(name);
    expect(passes(name, body)).toBe(true);
    mutate(body);
    expect(passes(name, body)).toBe(false);
  });
});

describe("fixture の前提", () => {
  it("patient_entries には受診日が1件以上あり、日付と受付の時刻だけを持つ", () => {
    const body = fixtureBody("patient_entries") as {
      visits: Array<Record<string, unknown>>;
    };
    expect(body.visits.length).toBeGreaterThanOrEqual(1);
    for (const visit of body.visits) {
      expect(Object.keys(visit).sort()).toEqual(["received_at", "visit_date"]);
    }
  });

  it("patient_entries の最後の記録は measured の体温を持つ（壊す操作の前提）", () => {
    const body = fixtureBody("patient_entries") as {
      entries: Array<{ answers: Array<{ value: string }> }>;
    };
    expect(body.entries[body.entries.length - 1].answers[0].value).toBe(
      "measured",
    );
  });
});
