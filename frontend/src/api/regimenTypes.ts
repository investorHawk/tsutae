/**
 * D4 レジメンの下書き・確認・採用の API の型（docs/architecture.md §8・9c、
 * backend/tsutae/api/doctor_regimen_drafts.py）。欄の id は backend の `field_ids` の形
 * （`basic.cycle_days`・`drugs.<row_id>.days`・`notes`）。
 */
import type { AnswerType } from "./types";

export type Route = "infusion" | "oral" | "pump";
/** 欄の出どころ: 先生の文から／標準の値（未確認）／先生が直接入れた。 */
export type FieldSource = "doctor_text" | "standard" | "doctor_edit";
export type DraftStatus = "open" | "working" | "adopted" | "discarded";
export type RowSection = "drugs" | "side_effects" | "questions";

export interface DayRange {
  start: number;
  end: number;
}

export interface RegimenBasic {
  display_name: string | null;
  code: string | null;
  target: string | null;
  cycle_days: number | null;
}

export interface DrugRow {
  row_id: string;
  name: string | null;
  route: Route | null;
  days: DayRange[];
  times_per_day: number | null;
  start_note: string | null;
}

export interface SideEffectRow {
  row_id: string;
  phrases: string[];
  ctcae_terms: string[];
  question_key: string | null;
}

export interface QuestionRow {
  row_id: string;
  key: string | null;
  label: string | null;
  text: string | null;
  answer_type: AnswerType | null;
}

/** 下書きのフォーム（描画用の文 prose は返らない）。 */
export interface RegimenFormValues {
  basic: RegimenBasic;
  drugs: DrugRow[];
  side_effects: SideEffectRow[];
  questions: QuestionRow[];
  notes: string;
}

/** 欄の id と理由（message に入力の文面は入らない）。 */
export interface FieldIssue {
  field_id: string;
  code: string;
  message: string;
}

/** Claude が先生に聞いた1問。画面は field_id の欄（か節）を赤枠にし、選択肢を出す。 */
export interface ChatAsk {
  field_id: string;
  question: string;
  options: string[];
}

/** 先生の文。 */
export interface DoctorChatRow {
  role: "doctor";
  text: string;
  generation: number;
  at: string;
}

/**
 * Claude の返答。changed は変えた欄の id（札にして押すとその欄へ）、proposed は足した
 * 質問の key。返答の文に個人を特定しうる表現の疑いがあれば text は固定の文で
 * reply_hidden=true。
 */
export interface AssistantChatRow {
  role: "assistant";
  text: string;
  changed: string[];
  ask: ChatAsk | null;
  proposed: string[];
  reply_hidden: boolean;
  generation: number;
  at: string;
}

/** 往復の失敗（kind=turn_failed。reason は timeout・max_turns・internal_error など）。 */
export interface SystemChatRow {
  role: "system";
  kind: string;
  reason: string;
  generation: number;
  at: string;
}

/** 会話の1行（院内の画面だけに出る。採用・破棄で消える）。 */
export type ChatRow = DoctorChatRow | AssistantChatRow | SystemChatRow;

/** GET regimen-drafts の1件。version は採用で作る版（新規は1、既存は N+1）。 */
export interface RegimenDraftSummary {
  id: number;
  regimen: string | null;
  skill_name: string | null;
  display_name: string | null;
  base_version: number | null;
  version: number;
  status: DraftStatus;
  updated_at: string;
}

export interface RegimenDraft extends RegimenDraftSummary {
  generation: number;
  form: RegimenFormValues;
  sources: Record<string, FieldSource>;
  chat: ChatRow[];
  /** 採用の前に要る欄の欠け（ピンクの欄）。 */
  missing: FieldIssue[];
  /** 患者のいるレジメンの版 N+1（1コースの日数・薬の Day・抜去日を変えられない）。 */
  schedule_locked: boolean;
  created_at: string;
}

export interface RegimenDraftsResponse {
  drafts: RegimenDraftSummary[];
}

export interface RegimenDraftResponse {
  draft: RegimenDraft;
}

/** POST regimen-drafts。新規は {from: "new"}、既存は {skill: "regimen-folfox"}。 */
export type CreateRegimenDraftRequest = { from: "new" } | { skill: string };

export interface CreateRegimenDraftResponse extends RegimenDraftResponse {
  /** false なら同じレジメンの開いた下書きを返した。 */
  created: boolean;
}

export interface FieldChange {
  field_id: string;
  value: unknown;
}

export interface RowAdd {
  section: RowSection;
  row_id: string;
}

/** PATCH .../fields。行の削除（`drugs.<row_id>`）→ 追加 → 欄の変更 の順に当たる。 */
export interface PatchRegimenFieldsRequest {
  changes?: FieldChange[];
  adds?: RowAdd[];
  deletes?: string[];
}

/** POST .../turns（Claude の1往復。応答まで待つ。上限はサーバーの 90 秒）。 */
export interface RegimenTurnRequest {
  text: string;
}

/**
 * turn_error は成功なら null。時間切れ・失敗なら timeout・max_turns・max_budget・
 * sdk_error・internal_error など（下書きは open に戻り、会話に失敗の行がある）、
 * 遅れた結果を捨てたら discarded。
 */
export interface RegimenTurnResponse extends RegimenDraftResponse {
  turn_error: string | null;
}

export interface AiValue {
  field_id: string;
  label: string;
  value: unknown;
  source: "doctor_text" | "standard";
}

export interface SkillMarkdown {
  /** full = 新規の全文、diff = 版 N との unified diff。 */
  kind: "full" | "diff";
  text: string;
}

export interface PatientPreviewQuestion {
  key: string | null;
  label: string | null;
  text: string | null;
  answer_type: AnswerType | null;
}

/** GET .../preview。issues が空でなければ skill_md は null（採用できない）。 */
export interface RegimenPreview {
  draft_id: number;
  skill_name: string | null;
  base_version: number | null;
  version: number;
  ai_values: AiValue[];
  skill_md: SkillMarkdown | null;
  patient_preview: PatientPreviewQuestion[];
  issues: FieldIssue[];
  confirm_token: string;
}

export interface AdoptRegimenRequest {
  confirm_token: string;
  ai_values_confirmed: boolean;
}

export interface AdoptRegimenResponse {
  ok: true;
  skill_name: string;
  version: number;
  regimen: string;
}
