/**
 * 医師 API（docs/architecture.md §8 医師・types.ts）の 2xx 応答の検査。
 * types.ts で `T | null`（? なし）の項目は「存在して null か T」だけを許す（省略は不正）。
 * `?` の項目（Course の予定日など）だけ省略を許す。日時は +09:00 付き ISO 8601、
 * 日付は暦に実在する YYYY-MM-DD。合わなければ invalid_response（§9 W2b の決定）。
 * {ok} の応答は ok === true だけを成功とする（{ok:false} を成功と誤認しない）。
 */
import {
  FEVER_VALUES,
  REGIMENS,
  TEMPERATURE_MAX,
  TEMPERATURE_MIN,
  THREE_LEVEL_VALUES,
  type Course,
  type EntryKind,
  type OpenVisitStatus,
  type SkillChangeStatus,
  type VisitStatus,
} from "./types";
import {
  type Item,
  codePointLength,
  everyItem,
  hasNullable,
  isBool,
  isInt,
  isIsoDate,
  isIsoDateTime,
  isOptInt,
  isOptIsoDate,
  isPositiveInt,
  isString,
  oneOf,
} from "./validate";

/** Course.note の上限（schemas.py。Python の文字数＝code point）。 */
export const COURSE_NOTE_MAX = 200;

export const VISIT_STATUSES: readonly VisitStatus[] = [
  "generating",
  "ready",
  "printed",
  "failed",
];
/** 印刷待ち一覧に出る状態（W3 後の決定。printed は出ない）。 */
export const OPEN_VISIT_STATUSES: readonly OpenVisitStatus[] = [
  "generating",
  "ready",
  "failed",
];
const SKILL_CHANGE_STATUSES: readonly SkillChangeStatus[] = [
  "pending",
  "approved",
  "rejected",
  "failed",
];

export const isVisitStatus = oneOf(VISIT_STATUSES);
export const isOpenVisitStatus = oneOf(OPEN_VISIT_STATUSES);
const isSkillChangeStatus = oneOf(SKILL_CHANGE_STATUSES);

/** {ok: true}。ok が false・欠落・true 以外なら不正。 */
export function isOkTrue(v: Item): boolean {
  return v.ok === true;
}

/** approve の応答 {ok: true, new_version}。new_version は必須で 1 以上の整数。 */
export function isApproveResponse(v: Item): boolean {
  return v.ok === true && isPositiveInt(v.new_version);
}

/** 印刷待ち一覧の1件。受付番号は必ずあり、状態は generating・ready・failed だけ。 */
export function isVisitSummary(v: Item): boolean {
  return (
    isInt(v.id) &&
    isString(v.reception_no) &&
    isString(v.patient_id) &&
    isOpenVisitStatus(v.status) &&
    isBool(v.fallback) &&
    isIsoDateTime(v.created_at) &&
    isIsoDateTime(v.expires_at) &&
    isInt(v.unprocessed_count)
  );
}

/** 患者一覧の1件。最後の記録日・今のコース・次回受診は nullable（省略は不正）。 */
export function isDoctorPatient(v: Item): boolean {
  return (
    isString(v.id) &&
    oneOf(REGIMENS)(v.regimen) &&
    isIsoDateTime(v.created_at) &&
    isString(v.register_url) &&
    hasNullable("last_record_date", isIsoDate)(v) &&
    hasNullable("current_course_no", isPositiveInt)(v) &&
    hasNullable("next_visit", isIsoDate)(v)
  );
}

/** 患者の画面の受診1件。受付番号は印刷済み・期限切れで null。状態は4つとも出る。 */
export function isPatientVisit(v: Item): boolean {
  return (
    isInt(v.id) &&
    hasNullable("reception_no", isString)(v) &&
    isIsoDate(v.visit_date) &&
    isIsoDateTime(v.created_at) &&
    isVisitStatus(v.status) &&
    isBool(v.fallback) &&
    isBool(v.report_available) &&
    isInt(v.unprocessed_count)
  );
}

const ENTRY_KINDS: readonly EntryKind[] = [
  "too_sick",
  "answers",
  "free_text",
  "mixed",
];
const isAnswerValue = oneOf([...THREE_LEVEL_VALUES, ...FEVER_VALUES]);

/** measured なら体温（範囲内の数）、それ以外は null（schemas.py ClosedAnswer）。 */
function fitsTemperature(v: Item): boolean {
  if (v.value !== "measured") {
    return v.temperature === null;
  }
  const t = v.temperature;
  return (
    typeof t === "number" &&
    Number.isFinite(t) &&
    t >= TEMPERATURE_MIN &&
    t <= TEMPERATURE_MAX
  );
}

function isDoctorEntryAnswer(v: Item): boolean {
  return (
    isString(v.question_key) && isAnswerValue(v.value) && fitsTemperature(v)
  );
}

/** 患者の画面の記録1件。原文は無く has_free_text だけ。 */
export function isDoctorEntry(v: Item): boolean {
  return (
    isInt(v.id) &&
    isIsoDateTime(v.recorded_at) &&
    isIsoDate(v.record_date) &&
    oneOf(ENTRY_KINDS)(v.kind) &&
    isBool(v.by_proxy) &&
    everyItem(isDoctorEntryAnswer)(v.answers) &&
    isBool(v.has_free_text)
  );
}

function isOptNote(v: unknown): boolean {
  return (
    v === undefined ||
    v === null ||
    (isString(v) && codePointLength(v) <= COURSE_NOTE_MAX)
  );
}

/** Course（schemas.py）: course_no ≥ 1、日付は YYYY-MM-DD、note は200字まで。 */
export function isCourse(v: Item): boolean {
  return (
    isOptInt(v.id) &&
    isString(v.patient_id) &&
    isPositiveInt(v.course_no) &&
    isIsoDate(v.infusion_date) &&
    isOptIsoDate(v.planned_date) &&
    isOptIsoDate(v.next_visit) &&
    isOptNote(v.note)
  );
}

/** POST courses の応答: 保存した Course（送った患者・コース番号と同じもの）。 */
export function isSavedCourse(sent: Course) {
  return (v: Item): boolean =>
    isCourse(v) &&
    v.patient_id === sent.patient_id &&
    v.course_no === sent.course_no;
}

export function isSkillInfo(v: Item): boolean {
  return isString(v.name) && isInt(v.version);
}

/** 読めない Skill {name, error_code, required}（GET skills の invalid）。 */
export function isInvalidSkill(v: Item): boolean {
  return isString(v.name) && isString(v.error_code) && isBool(v.required);
}

const isNumber = (x: unknown): boolean => typeof x === "number";

/** 一覧の1件。requested_text は必須の文字列、nullable の項目も省略は不正。 */
export function isSkillChange(v: Item): boolean {
  return (
    isInt(v.id) &&
    isString(v.skill_name) &&
    isSkillChangeStatus(v.status) &&
    isString(v.requested_text) &&
    hasNullable("diff", isString)(v) &&
    isInt(v.base_version) &&
    hasNullable("new_version", isInt)(v) &&
    hasNullable("error_code", isString)(v) &&
    isIsoDateTime(v.created_at) &&
    hasNullable("decided_at", isIsoDateTime)(v)
  );
}

/** D5 の1件。nullable の項目も省略は不正。 */
export function isPipelineEvent(v: Item): boolean {
  return (
    isIsoDateTime(v.ts) &&
    isString(v.event) &&
    hasNullable("hook_name", isString)(v) &&
    hasNullable("agent_type", isString)(v) &&
    hasNullable("tool_name", isString)(v) &&
    hasNullable("decision", isString)(v) &&
    hasNullable("duration_ms", isNumber)(v)
  );
}

/**
 * 疑われた語の位置の列。各位置は 0 ≤ start < end ≤ 文の長さ（code point）で、
 * 位置順に重ならずに並ぶ（画面がそのまま切り分けて <mark> にできる）。
 */
export function isTextMarks(marks: unknown, text: string): boolean {
  if (!everyItem((m) => isInt(m.start) && isInt(m.end))(marks)) {
    return false;
  }
  const length = codePointLength(text);
  let last = 0;
  for (const m of marks as Array<{ start: number; end: number }>) {
    if (m.start < last || m.end <= m.start || m.end > length) {
      return false;
    }
    last = m.end;
  }
  return true;
}

export function isUnprocessedItem(v: Item): boolean {
  return (
    isInt(v.entry_id) &&
    isIsoDate(v.record_date) &&
    isString(v.reason) &&
    isString(v.text) &&
    isTextMarks(v.marks, v.text)
  );
}

/** POST skill-changes の応答 {id, status, diff}。 */
export function isCreateSkillChangeResponse(v: Item): boolean {
  return (
    isInt(v.id) &&
    isSkillChangeStatus(v.status) &&
    hasNullable("diff", isString)(v)
  );
}

/** POST patients の応答 {id, register_url}。 */
export function isCreatePatientResponse(v: Item): boolean {
  return isString(v.id) && isString(v.register_url);
}

/** 本文の key が isItem に合う要素の配列であること。 */
const hasList =
  (key: string, isItem: (item: Item) => boolean) =>
  (v: Item): boolean =>
    everyItem(isItem)(v[key]);

export const isPatientsResponse = hasList("patients", isDoctorPatient);
export const isCoursesResponse = hasList("courses", isCourse);
export const isVisitsResponse = hasList("visits", isVisitSummary);
export const isUnprocessedResponse = hasList("entries", isUnprocessedItem);
export const isPatientVisitsResponse = hasList("visits", isPatientVisit);
/** 患者の画面の記録 {entries, total}。total は 0 以上の整数。 */
export function isPatientEntriesSummaryResponse(v: Item): boolean {
  return everyItem(isDoctorEntry)(v.entries) && isInt(v.total) && v.total >= 0;
}
/** GET skills {skills, invalid}。invalid は空でも必ずある（W3 後の決定）。 */
export function isSkillsResponse(v: Item): boolean {
  return (
    everyItem(isSkillInfo)(v.skills) && everyItem(isInvalidSkill)(v.invalid)
  );
}
export const isSkillChangesResponse = hasList("skill_changes", isSkillChange);

const isAnswerType = oneOf(["three_level", "temperature"] as const);

/** Skill の中身の質問 {key, text, answer_type}。 */
function isSkillQuestion(v: Item): boolean {
  return isString(v.key) && isString(v.text) && isAnswerType(v.answer_type);
}

/** GET skills/{name} {name, version, description, questions, text}。 */
export function isSkillContentResponse(v: Item): boolean {
  return (
    isString(v.name) &&
    isInt(v.version) &&
    isString(v.description) &&
    everyItem(isSkillQuestion)(v.questions) &&
    isString(v.text)
  );
}

/** D5 の応答 {status, events}。 */
export function isPipelineEventsResponse(v: Item): boolean {
  return isVisitStatus(v.status) && everyItem(isPipelineEvent)(v.events);
}
