/**
 * 医師 API（docs/architecture.md §8 医師・types.ts）の 2xx 応答の検査。
 * types.ts で `T | null`（? なし）の項目は「存在して null か T」だけを許す（省略は不正）。
 * `?` の項目（Course の予定日など）だけ省略を許す。日時は +09:00 付き ISO 8601、
 * 日付は暦に実在する YYYY-MM-DD。合わなければ invalid_response（§9 W2b の決定）。
 * {ok} の応答は ok === true だけを成功とする（{ok:false} を成功と誤認しない）。
 */
import {
  REGIMENS,
  type Course,
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

export function isDoctorPatient(v: Item): boolean {
  return (
    isString(v.id) &&
    oneOf(REGIMENS)(v.regimen) &&
    isIsoDateTime(v.created_at) &&
    isString(v.register_url)
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

export function isUnprocessedItem(v: Item): boolean {
  return (
    isInt(v.entry_id) &&
    isIsoDate(v.record_date) &&
    isString(v.reason) &&
    isString(v.text)
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
/** GET skills {skills, invalid}。invalid は空でも必ずある（W3 後の決定）。 */
export function isSkillsResponse(v: Item): boolean {
  return (
    everyItem(isSkillInfo)(v.skills) && everyItem(isInvalidSkill)(v.invalid)
  );
}
export const isSkillChangesResponse = hasList("skill_changes", isSkillChange);

/** D5 の応答 {status, events}。 */
export function isPipelineEventsResponse(v: Item): boolean {
  return isVisitStatus(v.status) && everyItem(isPipelineEvent)(v.events);
}
