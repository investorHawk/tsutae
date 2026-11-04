/**
 * D4 レジメンの欄の4つの状態（純関数）。色だけに頼らず、欄の下に文字の札も出す。
 *
 * - asked（Claude が聞いています・赤枠）: 会話の最後が Claude の ask で、その欄（か行・節）を
 *   指していて、先生がまだ直接入れていない
 * - missing（未入力・ピンク）: draft.missing にある必須の欄
 * - ai（AI が入れた・橙の点線）: 出どころが standard（標準の値）か doctor_text（先生の文から）
 * - doc（先生が入れた・青枠）: 出どころが doctor_edit
 *
 * 強さは asked > missing > ai > doc。
 */
import type {
  ChatAsk,
  FieldSource,
  PatchRegimenFieldsRequest,
  RegimenDraft,
} from "../../../api/regimenTypes";
import type { FieldErrors } from "./useRegimenDraft";

export type FieldState = "asked" | "missing" | "ai" | "doc" | "plain";

export const STATE_TAGS: Readonly<Record<FieldState, string>> = {
  asked: "Claude が聞いています",
  missing: "未入力（必須）",
  ai: "AI が入れた",
  doc: "先生が入れた",
  plain: "",
};

const AI_SOURCE_NOTES: Readonly<Record<string, string>> = {
  standard: "標準の値",
  doctor_text: "先生の文から",
};

/** 会話の最後が Claude の ask なら、その ask（答えるまで有効）。 */
export function activeAsk(draft: RegimenDraft): ChatAsk | null {
  const last = draft.chat[draft.chat.length - 1];
  return last && last.role === "assistant" ? last.ask : null;
}

/** ask の目印（下書きと会話の長さ。会話が伸びれば別の ask）。 */
export function askKeyOf(draft: RegimenDraft): string {
  return `${draft.id}:${draft.chat.length}`;
}

/**
 * まだ答えていない ask（赤枠・「確認へ進む」を止める）。会話の最後の ask でも、赤枠の欄を
 * 直接直した（answeredKey がこの ask の目印・ask の欄の出どころが doctor_edit）なら答えた
 * ことにする。サーバーは「答えた」を持たないので、画面で決める。
 */
export function openAsk(
  draft: RegimenDraft,
  answeredKey: string | null,
): ChatAsk | null {
  const ask = activeAsk(draft);
  if (!ask || answeredKey === askKeyOf(draft)) {
    return null;
  }
  return draft.sources[ask.field_id] === "doctor_edit" ? null : ask;
}

/** 直接編集がその ask の欄（行・節）に触れるか（欄の変更・行の追加と削除）。 */
export function patchTouchesAsk(
  ask: ChatAsk | null,
  body: PatchRegimenFieldsRequest,
): boolean {
  const ids = [
    ...(body.changes ?? []).map((c) => c.field_id),
    ...(body.adds ?? []).map((a) => `${a.section}.${a.row_id}`),
    ...(body.deletes ?? []),
  ];
  return ids.some((id) => askCovers(ask, id));
}

/** ask がその欄（か、その欄を含む行・節）を指しているか。 */
export function askCovers(ask: ChatAsk | null, fieldId: string): boolean {
  if (!ask) {
    return false;
  }
  return fieldId === ask.field_id || fieldId.startsWith(`${ask.field_id}.`);
}

function isAiSource(source: FieldSource | undefined): boolean {
  return source === "standard" || source === "doctor_text";
}

export function fieldStateOf(
  draft: RegimenDraft,
  fieldId: string,
  ask: ChatAsk | null,
): FieldState {
  const source = draft.sources[fieldId];
  if (askCovers(ask, fieldId) && source !== "doctor_edit") {
    return "asked";
  }
  if (
    draft.missing.some((m) => m.field_id === fieldId && m.code === "required")
  ) {
    return "missing";
  }
  if (isAiSource(source)) {
    return "ai";
  }
  return source === "doctor_edit" ? "doc" : "plain";
}

/** 欄の下の札（AI の値は出どころも添える）。 */
export function stateTagOf(state: FieldState, source?: FieldSource): string {
  if (state === "ai" && source) {
    const note = AI_SOURCE_NOTES[source];
    return note ? `${STATE_TAGS.ai}（${note}）` : STATE_TAGS.ai;
  }
  return STATE_TAGS[state];
}

/** 節（basic・drugs など）の中で AI が入れた欄の数。 */
export function aiCountIn(draft: RegimenDraft, section: string): number {
  return Object.entries(draft.sources).filter(
    ([id, source]) =>
      (id === section || id.startsWith(`${section}.`)) && isAiSource(source),
  ).length;
}

/** 節の単位の欠け（「薬を1剤以上」「Day1 に点滴」など。欄の id が節の名前のもの）。 */
export function sectionIssues(
  draft: RegimenDraft,
  section: string,
): RegimenDraft["missing"] {
  return draft.missing.filter((m) => m.field_id === section);
}

const ROW_SECTIONS = new Set(["drugs", "side_effects", "questions"]);

/**
 * 節の見出しの下に出す理由: 節の名前の欄と、行の単位の欄（`drugs.<row_id>`・`drugs.#1`。
 * 行の節だけ。欄ごとの理由は欄の下に出る）。
 */
export function sectionErrors(
  fieldErrors: FieldErrors,
  section: string,
): string[] {
  return Object.entries(fieldErrors).flatMap(([id, messages]) => {
    const parts = id.split(".");
    const own =
      id === section ||
      (ROW_SECTIONS.has(section) && parts.length === 2 && parts[0] === section);
    return own ? [...messages] : [];
  });
}
