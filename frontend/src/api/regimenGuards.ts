/**
 * D4 レジメンの下書き・確認・採用の 2xx 応答の検査（regimenTypes.ts）。doctorGuards と同じ
 * 決まり: `T | null`（? なし）の項目は「存在して null か T」だけを許す。日時は +09:00 付き。
 * 合わなければ invalid_response（§9 W2b の決定）。
 */
import type { DraftStatus, FieldSource, Route } from "./regimenTypes";
import {
  type Item,
  everyItem,
  has,
  hasNullable,
  isBool,
  isInt,
  isIsoDateTime,
  isPositiveInt,
  isRecord,
  isString,
  oneOf,
} from "./validate";

const DRAFT_STATUSES: readonly DraftStatus[] = [
  "open",
  "working",
  "adopted",
  "discarded",
];
const SOURCES: readonly FieldSource[] = [
  "doctor_text",
  "standard",
  "doctor_edit",
];
const ROUTES: readonly Route[] = ["infusion", "oral", "pump"];

const isDraftStatus = oneOf(DRAFT_STATUSES);
const isSource = oneOf(SOURCES);
const isAiSource = oneOf(["standard"] as const);
const isRoute = oneOf(ROUTES);
const isAnswerType = oneOf(["three_level", "temperature"] as const);
const isSkillKind = oneOf(["full", "diff"] as const);

const isStringList = (v: unknown): boolean =>
  Array.isArray(v) && v.every(isString);

const nullableString = (key: string) => hasNullable(key, isString);
const nullableInt = (key: string) => hasNullable(key, isInt);

function isDayRange(v: Item): boolean {
  return isPositiveInt(v.start) && isPositiveInt(v.end);
}

function isBasic(v: Item): boolean {
  return (
    nullableString("display_name")(v) &&
    nullableString("code")(v) &&
    nullableString("target")(v) &&
    nullableInt("cycle_days")(v)
  );
}

function isDrug(v: Item): boolean {
  return (
    isString(v.row_id) &&
    nullableString("name")(v) &&
    hasNullable("route", isRoute)(v) &&
    everyItem(isDayRange)(v.days) &&
    nullableInt("times_per_day")(v) &&
    nullableString("start_note")(v)
  );
}

function isSideEffect(v: Item): boolean {
  return (
    isString(v.row_id) &&
    isStringList(v.phrases) &&
    isStringList(v.ctcae_terms) &&
    nullableString("question_key")(v)
  );
}

function isQuestionRow(v: Item): boolean {
  return (
    isString(v.row_id) &&
    nullableString("key")(v) &&
    nullableString("label")(v) &&
    nullableString("text")(v) &&
    hasNullable("answer_type", isAnswerType)(v)
  );
}

function isForm(v: unknown): boolean {
  return (
    isRecord(v) &&
    isRecord(v.basic) &&
    isBasic(v.basic) &&
    everyItem(isDrug)(v.drugs) &&
    everyItem(isSideEffect)(v.side_effects) &&
    everyItem(isQuestionRow)(v.questions) &&
    isString(v.notes) &&
    !has(v, "prose")
  );
}

function isSources(v: unknown): boolean {
  return isRecord(v) && Object.values(v).every(isSource);
}

/** 欄の id と理由。 */
export function isFieldIssue(v: Item): boolean {
  return isString(v.field_id) && isString(v.code) && isString(v.message);
}

const isNonNegativeInt = (v: unknown): boolean => isInt(v) && v >= 0;

function isChatAsk(v: unknown): boolean {
  return (
    isRecord(v) &&
    isString(v.field_id) &&
    isString(v.question) &&
    isStringList(v.options) &&
    (v.options as unknown[]).length >= 2
  );
}

/** 会話の行に共通の generation・at。 */
function isChatMeta(v: Item): boolean {
  return isNonNegativeInt(v.generation) && isIsoDateTime(v.at);
}

function isAssistantRow(v: Item): boolean {
  return (
    isString(v.text) &&
    isStringList(v.changed) &&
    hasNullable("ask", isChatAsk)(v) &&
    isStringList(v.proposed) &&
    isBool(v.reply_hidden)
  );
}

/** 会話の1行（role ごとに形を見る。未知の role は拒む）。 */
function isChatRow(v: Item): boolean {
  if (!isChatMeta(v)) {
    return false;
  }
  switch (v.role) {
    case "doctor":
      return isString(v.text);
    case "assistant":
      return isAssistantRow(v);
    case "system":
      return isString(v.kind) && isString(v.reason);
    default:
      return false;
  }
}

/** 一覧の1件。 */
export function isRegimenDraftSummary(v: Item): boolean {
  return (
    isPositiveInt(v.id) &&
    nullableString("regimen")(v) &&
    nullableString("skill_name")(v) &&
    nullableString("display_name")(v) &&
    hasNullable("base_version", isPositiveInt)(v) &&
    isPositiveInt(v.version) &&
    isDraftStatus(v.status) &&
    isIsoDateTime(v.updated_at)
  );
}

function isRegimenDraft(v: unknown): boolean {
  return (
    isRecord(v) &&
    isRegimenDraftSummary(v) &&
    isInt(v.generation) &&
    v.generation >= 0 &&
    isForm(v.form) &&
    isSources(v.sources) &&
    everyItem(isChatRow)(v.chat) &&
    everyItem(isFieldIssue)(v.missing) &&
    isBool(v.schedule_locked) &&
    isIsoDateTime(v.created_at)
  );
}

/** GET regimen-drafts {drafts}。 */
export function isRegimenDraftsResponse(v: Item): boolean {
  return everyItem(isRegimenDraftSummary)(v.drafts);
}

/** GET regimen-drafts/{id}・PATCH .../fields {draft}。 */
export function isRegimenDraftResponse(v: Item): boolean {
  return isRegimenDraft(v.draft);
}

/** POST .../turns {draft, turn_error}。 */
export function isRegimenTurnResponse(v: Item): boolean {
  return isRegimenDraft(v.draft) && hasNullable("turn_error", isString)(v);
}

/** POST regimen-drafts {draft, created}。 */
export function isCreateRegimenDraftResponse(v: Item): boolean {
  return isRegimenDraft(v.draft) && isBool(v.created);
}

function isAiValue(v: Item): boolean {
  return (
    isString(v.field_id) &&
    isString(v.label) &&
    has(v, "value") &&
    isAiSource(v.source)
  );
}

function isPatientPreview(v: Item): boolean {
  return (
    nullableString("key")(v) &&
    nullableString("label")(v) &&
    nullableString("text")(v) &&
    hasNullable("answer_type", isAnswerType)(v)
  );
}

function isSkillMarkdown(v: unknown): boolean {
  return isRecord(v) && isSkillKind(v.kind) && isString(v.text);
}

const TOKEN = /^[0-9a-f]{64}$/;

/** GET .../preview。issues があれば skill_md は null。 */
export function isRegimenPreviewResponse(v: Item): boolean {
  const issues = v.issues;
  return (
    isPositiveInt(v.draft_id) &&
    nullableString("skill_name")(v) &&
    hasNullable("base_version", isPositiveInt)(v) &&
    isPositiveInt(v.version) &&
    everyItem(isAiValue)(v.ai_values) &&
    hasNullable("skill_md", isSkillMarkdown)(v) &&
    everyItem(isPatientPreview)(v.patient_preview) &&
    everyItem(isFieldIssue)(issues) &&
    (!Array.isArray(issues) || issues.length === 0 || v.skill_md === null) &&
    isString(v.confirm_token) &&
    TOKEN.test(v.confirm_token)
  );
}

/** POST .../adopt {ok: true, skill_name, version, regimen}。 */
export function isAdoptRegimenResponse(v: Item): boolean {
  return (
    v.ok === true &&
    isString(v.skill_name) &&
    isPositiveInt(v.version) &&
    isString(v.regimen)
  );
}
