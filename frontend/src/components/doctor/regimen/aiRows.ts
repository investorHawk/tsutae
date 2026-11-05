/**
 * 確認の画面の「AI が入れた値」の行（純関数）。一覧の1行は、行の節（薬・副作用・質問）は
 * 行ごとに1つ、基本と補足の指示は欄ごとに1つ。AI が入れた値は標準の値（standard）だけで、
 * 先生の文から（doctor_text）の欄は一覧に出ない（backend の ai_values）。
 */
import type {
  AiValue,
  FieldChange,
  FieldSource,
  PatchRegimenFieldsRequest,
  RegimenDraft,
  RegimenFormValues,
  RowSection,
} from "../../../api/regimenTypes";
import { ROUTE_LABELS } from "./DayBar";
import { ROW_HEADS } from "./fieldLabels";
import { emptyValueOf, valueText } from "./fieldValues";
import { ANSWER_TYPE_LABELS } from "./QuestionsSection";

const LABEL_SEP = " — ";
const ROW_SECTIONS: ReadonlySet<string> = new Set<RowSection>([
  "drugs",
  "side_effects",
  "questions",
]);

export interface AiRow {
  /** 行の id（`side_effects.<row_id>`）か欄の id（`basic.target`・`notes`） */
  key: string;
  /** 行の節（基本・補足の指示は null） */
  section: RowSection | null;
  /** 行の名前（label の「 — 」より前） */
  name: string;
  /** 一覧の欄の列（同じ名前の副作用と質問を見分ける。例: 「副作用 · 下痢」） */
  where: string;
  /** 値の文（「欄の名前: 値」を「／」でつなぐ。基本・補足の指示は値だけ） */
  text: string;
  fieldIds: readonly string[];
}

function isStandard(source: FieldSource | undefined): boolean {
  return source === "standard";
}

/** 欄の id → 一覧の行の鍵（行の節は行の id、ほかは欄の id のまま）。 */
function rowKeyOf(fieldId: string): string {
  const [section, rowId, name] = fieldId.split(".");
  return ROW_SECTIONS.has(section) && rowId && name
    ? `${section}.${rowId}`
    : fieldId;
}

function splitLabel(label: string): { name: string; field: string | null } {
  const at = label.lastIndexOf(LABEL_SEP);
  return at < 0
    ? { name: label, field: null }
    : { name: label.slice(0, at), field: label.slice(at + LABEL_SEP.length) };
}

/** 質問の key → 短い名前（対応する質問の欄に key をそのまま出さないため）。 */
export type QuestionLabels = readonly {
  key: string | null;
  label: string | null;
}[];

/** 医師に見せる値（経路・回答の型・対応する質問は内部の値を日本語にする）。 */
function displayValue(value: AiValue, questions: QuestionLabels): unknown {
  const name = value.field_id.split(".").pop();
  const raw = value.value;
  if (name === "route") {
    return ROUTE_LABELS[raw as keyof typeof ROUTE_LABELS] ?? raw;
  }
  if (name === "answer_type") {
    return ANSWER_TYPE_LABELS[raw as keyof typeof ANSWER_TYPE_LABELS] ?? raw;
  }
  if (name === "question_key") {
    return questions.find((q) => q.key === raw)?.label ?? raw;
  }
  return raw;
}

function partOf(value: AiValue, questions: QuestionLabels): string {
  const { field } = splitLabel(value.label);
  const text = valueText(displayValue(value, questions));
  return field === null ? text : `${field}: ${text}`;
}

/** 質問の key は医師に見せない（plan §1。削除の対象の fieldIds には残す）。 */
function isShown(value: AiValue): boolean {
  return !/^questions\.[^.]+\.key$/.test(value.field_id);
}

function rowOf(
  key: string,
  values: readonly AiValue[],
  questions: QuestionLabels,
): AiRow {
  const { name } = splitLabel(values[0].label);
  const [head, rowId] = key.split(".");
  const section = rowId && ROW_SECTIONS.has(head) ? (head as RowSection) : null;
  return {
    key,
    section,
    name,
    where: section ? `${ROW_HEADS[section]} · ${name}` : name,
    text: values
      .filter(isShown)
      .map((v) => partOf(v, questions))
      .join("／"),
    fieldIds: values.map((v) => v.field_id),
  };
}

/** AiValue[] を行にまとめる（並びは入力のまま）。 */
export function aiRowsOf(
  values: readonly AiValue[],
  questions: QuestionLabels = [],
): AiRow[] {
  const groups = new Map<string, AiValue[]>();
  for (const value of values) {
    const key = rowKeyOf(value.field_id);
    groups.set(key, [...(groups.get(key) ?? []), value]);
  }
  return [...groups].map(([key, group]) => rowOf(key, group, questions));
}

/** 出どころの一覧から、確認の画面の行の数を数える（aiRowsOf と同じ数え方）。 */
export function aiRowCountOf(
  sources: Readonly<Record<string, FieldSource>>,
): number {
  const ids = Object.keys(sources).filter((id) => isStandard(sources[id]));
  return new Set(ids.map(rowKeyOf)).size;
}

function isFilled(value: unknown): boolean {
  return !(
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}

function formRowOf(
  form: RegimenFormValues,
  section: RowSection,
  key: string,
): Readonly<Record<string, unknown>> | undefined {
  const rows: readonly { row_id: string }[] = form[section];
  return rows.find((r) => `${section}.${r.row_id}` === key);
}

/** 行の値が入っている欄が全て標準の値か（出どころの無い欄は既存の版の値なので違う）。 */
function allStandard(
  draft: RegimenDraft,
  key: string,
  row: Readonly<Record<string, unknown>>,
): boolean {
  return Object.entries(row)
    .filter(([name, value]) => name !== "row_id" && isFilled(value))
    .every(([name]) => isStandard(draft.sources[`${key}.${name}`]));
}

/** その key を指す副作用の question_key を空にする変更（サーバーの unknown_question を避ける）。 */
function questionRefChanges(
  form: RegimenFormValues,
  key: unknown,
): FieldChange[] {
  return form.side_effects
    .filter((s) => isFilled(key) && s.question_key === key)
    .map((s) => ({
      field_id: `side_effects.${s.row_id}.question_key`,
      value: null,
    }));
}

export interface DeletePatch {
  body: PatchRegimenFieldsRequest;
  /** 前の理由を消す欄の id */
  fieldIds: readonly string[];
}

function deleteWholeRow(
  draft: RegimenDraft,
  row: AiRow,
  section: RowSection,
  formRow: Readonly<Record<string, unknown>>,
): DeletePatch {
  const refs =
    section === "questions" ? questionRefChanges(draft.form, formRow.key) : [];
  return {
    body: {
      deletes: [row.key],
      ...(refs.length > 0 ? { changes: refs } : {}),
    },
    fieldIds: [section, row.key, ...refs.map((c) => c.field_id)],
  };
}

function clearStandardFields(
  draft: RegimenDraft,
  row: AiRow,
  formRow: Readonly<Record<string, unknown>> | undefined,
): DeletePatch {
  const ids = row.fieldIds.filter((id) => isStandard(draft.sources[id]));
  const clearsKey =
    row.section === "questions" && ids.includes(`${row.key}.key`);
  const refs = clearsKey ? questionRefChanges(draft.form, formRow?.key) : [];
  const changes = [
    ...ids.map((id) => ({ field_id: id, value: emptyValueOf(id) })),
    ...refs,
  ];
  return { body: { changes }, fieldIds: changes.map((c) => c.field_id) };
}

/**
 * 一覧の「削除」が送る PATCH。行の節で値が入っている欄が全て標準の値なら行ごと消し、先生の
 * 欄が混ざる行と基本・補足の指示は標準の値の欄だけを空にする。質問の行か key を消すときは、
 * その key を指す副作用の question_key も同じ PATCH で空にする。体温の質問はサーバーが
 * temperature_required で拒む（画面は失敗の案内を出す）。
 */
export function deletePatchOf(draft: RegimenDraft, row: AiRow): DeletePatch {
  const { section } = row;
  const formRow = section ? formRowOf(draft.form, section, row.key) : undefined;
  if (section && formRow && allStandard(draft, row.key, formRow)) {
    return deleteWholeRow(draft, row, section, formRow);
  }
  return clearStandardFields(draft, row, formRow);
}
