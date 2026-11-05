/**
 * 患者 API（§8 患者）の 2xx 応答の検査。契約で列挙された項目は全て存在を必須にする
 * （nullable の項目は「存在して null」を許す。省略は不正）。ClosedAnswer の規則
 * （measured のときだけ体温 30.0〜45.0）と、質問・回答の key の重複も見る。
 * 日時は +09:00 付き ISO 8601、日付は暦に実在する YYYY-MM-DD。
 * 合わなければ invalid_response（画面は error.generic を出す。真っ白にしない）。
 */
import {
  type AnswerType,
  type AnswerValue,
  type EntryKind,
  FEVER_VALUES,
  TEMPERATURE_MAX,
  TEMPERATURE_MIN,
  THREE_LEVEL_VALUES,
} from "./types";
import {
  type Item,
  everyItem,
  has,
  hasNullable,
  isBool,
  isInt,
  isIsoDate,
  isIsoDateTime,
  isString,
  oneOf,
} from "./validate";

const ANSWER_TYPES: readonly AnswerType[] = ["three_level", "temperature"];
const ANSWER_VALUES: readonly AnswerValue[] = [
  ...THREE_LEVEL_VALUES,
  ...FEVER_VALUES,
];
const ENTRY_KINDS: readonly EntryKind[] = [
  "too_sick",
  "answers",
  "free_text",
  "mixed",
];

const isStringList = (v: unknown): boolean =>
  Array.isArray(v) && v.every(isString);

/** 項目が存在し、値が null か文字列。 */
function hasNullableString(v: Item, key: string): boolean {
  return hasNullable(key, isString)(v);
}

/** 配列の要素の key に重複が無い。 */
function uniqueBy(items: readonly Item[], key: string): boolean {
  const values = items.map((item) => item[key]);
  return new Set(values).size === values.length;
}

const isListWithUniqueKeys =
  (isItem: (item: Item) => boolean, key: string) =>
  (v: unknown): boolean =>
    everyItem(isItem)(v) && uniqueBy(v as Item[], key);

function isQuestion(v: Item): boolean {
  return (
    isString(v.key) && isString(v.text) && oneOf(ANSWER_TYPES)(v.answer_type)
  );
}

/**
 * GET questions: {skill_version, questions: Question[], today}（key は重複しない。
 * today はサーバーの今日の YYYY-MM-DD）
 */
export function isQuestionsResponse(v: Item): boolean {
  return (
    isString(v.skill_version) &&
    isListWithUniqueKeys(isQuestion, "key")(v.questions) &&
    isIsoDate(v.today)
  );
}

/** POST entries: {entry_id, notices: string[]} */
export function isCreateEntryResponse(v: Item): boolean {
  return isInt(v.entry_id) && isStringList(v.notices);
}

function isTemperature(v: unknown): boolean {
  return (
    typeof v === "number" &&
    Number.isFinite(v) &&
    v >= TEMPERATURE_MIN &&
    v <= TEMPERATURE_MAX
  );
}

/** ClosedAnswer の規則: measured なら体温（範囲内の数）、それ以外は null。 */
function fitsTemperatureRule(v: Item): boolean {
  if (!has(v, "temperature")) {
    return false;
  }
  return v.value === "measured"
    ? isTemperature(v.temperature)
    : v.temperature === null;
}

/** 記録の回答。question_text は記録時点の質問文（見つからなければ null）。 */
function isPatientAnswer(v: Item): boolean {
  return (
    isString(v.question_key) &&
    oneOf(ANSWER_VALUES)(v.value) &&
    fitsTemperatureRule(v) &&
    hasNullableString(v, "question_text")
  );
}

function isPatientEntry(v: Item): boolean {
  return (
    isInt(v.id) &&
    isIsoDateTime(v.recorded_at) &&
    isIsoDate(v.record_date) &&
    oneOf(ENTRY_KINDS)(v.kind) &&
    isBool(v.by_proxy) &&
    isString(v.skill_version) &&
    isListWithUniqueKeys(isPatientAnswer, "question_key")(v.answers) &&
    hasNullableString(v, "free_text")
  );
}

/** 受診日: {visit_date, received_at}（日付と受付の時刻だけ） */
function isPatientVisitDay(v: Item): boolean {
  return isIsoDate(v.visit_date) && isIsoDateTime(v.received_at);
}

/**
 * GET entries: {entries: PatientEntry[], visits: PatientVisitDay[]}（受診日は1日1件。
 * visit_date は重複しない）
 */
export function isPatientEntriesResponse(v: Item): boolean {
  return (
    everyItem(isPatientEntry)(v.entries) &&
    isListWithUniqueKeys(isPatientVisitDay, "visit_date")(v.visits)
  );
}

/** POST register: {ok: true} */
export function isOkTrue(v: Item): boolean {
  return v.ok === true;
}

/** GET push-config: 使えるときは公開鍵があり、使えないときは null。 */
export function isPushConfigResponse(v: Item): boolean {
  if (v.available === true) {
    return isString(v.public_key) && v.public_key !== "";
  }
  return v.available === false && v.public_key === null;
}

/** PUT push-subscription: {ok: true, notify_time}（JST の HH:MM。30 分刻み）。 */
export function isPushSubscriptionResponse(v: Item): boolean {
  return (
    v.ok === true &&
    isString(v.notify_time) &&
    /^(?:[01][0-9]|2[0-3]):(?:00|30)$/.test(v.notify_time)
  );
}

/** POST visit: {ok: true, message_key} */
export function isVisitResponse(v: Item): boolean {
  return v.ok === true && isString(v.message_key);
}
