/**
 * 医師 API（docs/architecture.md §8 医師・types.ts）の 2xx 応答の検査。
 * null を許す項目は null・省略を許す。合わなければ invalid_response（§9 W2b の決定）。
 * {ok} の応答は ok === true だけを成功とする（{ok:false} を成功と誤認しない）。
 */
import {
  REGIMENS,
  type Course,
  type SkillChangeStatus,
  type VisitStatus,
} from "./types";
import {
  type Item,
  codePointLength,
  everyItem,
  isBool,
  isInt,
  isIsoDate,
  isOptInt,
  isOptIsoDate,
  isOptNumber,
  isOptString,
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
const SKILL_CHANGE_STATUSES: readonly SkillChangeStatus[] = [
  "pending",
  "approved",
  "rejected",
  "failed",
];

export const isVisitStatus = oneOf(VISIT_STATUSES);
const isSkillChangeStatus = oneOf(SKILL_CHANGE_STATUSES);

/** {ok: true}。ok が false・欠落・true 以外なら不正。 */
export function isOkTrue(v: Item): boolean {
  return v.ok === true;
}

/** approve / reject の応答 {ok: true, new_version?}。new_version は 1 以上の整数か null・省略。 */
export function isDecideResponse(v: Item): boolean {
  return (
    v.ok === true &&
    (v.new_version === undefined ||
      v.new_version === null ||
      isPositiveInt(v.new_version))
  );
}

export function isVisitSummary(v: Item): boolean {
  return (
    isInt(v.id) &&
    isOptString(v.reception_no) &&
    isString(v.patient_id) &&
    isVisitStatus(v.status) &&
    isBool(v.fallback) &&
    isString(v.created_at) &&
    isString(v.expires_at) &&
    isInt(v.unprocessed_count)
  );
}

export function isDoctorPatient(v: Item): boolean {
  return (
    isString(v.id) &&
    oneOf(REGIMENS)(v.regimen) &&
    isString(v.created_at) &&
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

export function isSkillChange(v: Item): boolean {
  return (
    isInt(v.id) &&
    isString(v.skill_name) &&
    isSkillChangeStatus(v.status) &&
    isOptString(v.requested_text) &&
    isOptString(v.diff) &&
    isInt(v.base_version) &&
    isOptInt(v.new_version) &&
    isOptString(v.error_code) &&
    isString(v.created_at) &&
    isOptString(v.decided_at)
  );
}

export function isPipelineEvent(v: Item): boolean {
  return (
    isString(v.ts) &&
    isString(v.event) &&
    isOptString(v.hook_name) &&
    isOptString(v.agent_type) &&
    isOptString(v.tool_name) &&
    isOptString(v.decision) &&
    isOptNumber(v.duration_ms)
  );
}

export function isUnprocessedItem(v: Item): boolean {
  return (
    isInt(v.entry_id) &&
    isString(v.record_date) &&
    isString(v.reason) &&
    isString(v.text)
  );
}

/** POST skill-changes の応答 {id, status, diff}。 */
export function isCreateSkillChangeResponse(v: Item): boolean {
  return isInt(v.id) && isSkillChangeStatus(v.status) && isOptString(v.diff);
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
export const isSkillsResponse = hasList("skills", isSkillInfo);
export const isSkillChangesResponse = hasList("skill_changes", isSkillChange);

/** D5 の応答 {status, events}。 */
export function isPipelineEventsResponse(v: Item): boolean {
  return isVisitStatus(v.status) && everyItem(isPipelineEvent)(v.events);
}
