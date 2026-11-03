/**
 * API に出る型。backend/tsutae/schemas.py（pydantic）と docs/architecture.md §8 を写したもの。
 * 日付は "YYYY-MM-DD"、日時は ISO 8601（+09:00 付き）の文字列。
 */

export type IsoDate = string;
export type IsoDateTime = string;

// ---------------------------------------------------------------------------
// 基本の列挙（schemas.py）
// ---------------------------------------------------------------------------

export type Regimen = "FOLFOX" | "CAPOX";
export type ThreeLevel = "none" | "present" | "hard";
export type FeverValue = "not_measured" | "measured";
export type AnswerValue = ThreeLevel | FeverValue;
export type AnswerType = "three_level" | "temperature";
export type EntryKind = "too_sick" | "answers" | "free_text" | "mixed";
export type VisitStatus = "generating" | "ready" | "printed" | "failed";
export type SkillChangeStatus = "pending" | "approved" | "rejected" | "failed";

export const REGIMENS: readonly Regimen[] = ["FOLFOX", "CAPOX"];
export const THREE_LEVEL_VALUES: readonly ThreeLevel[] = [
  "none",
  "present",
  "hard",
];
export const FEVER_VALUES: readonly FeverValue[] = ["not_measured", "measured"];

// ---------------------------------------------------------------------------
// Skill と記録（schemas.py）
// ---------------------------------------------------------------------------

export interface Question {
  key: string;
  text: string;
  answer_type: AnswerType;
}

/** 体温の範囲（schemas.py ClosedAnswer: 30.0〜45.0）。 */
export const TEMPERATURE_MIN = 30;
export const TEMPERATURE_MAX = 45;

/** temperature は value が "measured" のときだけ付ける（それ以外は null か省略）。 */
export interface ClosedAnswer {
  question_key: string;
  value: AnswerValue;
  temperature?: number | null;
}

/** POST /api/patient/{pid}/entries の本文。too_sick のときは回答・自由記載を付けない。 */
export interface EntryCreate {
  too_sick?: boolean;
  by_proxy?: boolean;
  answers?: ClosedAnswer[];
  free_text?: string | null;
}

export interface Course {
  id?: number | null;
  patient_id: string;
  course_no: number;
  /** 実投与日 = Day1 */
  infusion_date: IsoDate;
  /** 予定日（延期の注記に使う） */
  planned_date?: IsoDate | null;
  next_visit?: IsoDate | null;
  note?: string | null;
}

// ---------------------------------------------------------------------------
// 共通のレスポンス
// ---------------------------------------------------------------------------

export interface OkResponse {
  ok: boolean;
}

/** 失敗時の本文。code は文面ではなくコード。 */
export interface ErrorResponse {
  error: string;
}

// ---------------------------------------------------------------------------
// 患者 API（§8 患者）
// ---------------------------------------------------------------------------

export interface RegisterRequest {
  pid: string;
}

/** GET /api/patient/strings。patient_strings.json そのもの（キー → 定型文）。 */
export type PatientStrings = Readonly<Record<string, string>>;

export interface QuestionsResponse {
  skill_version: string;
  questions: Question[];
}

export interface CreateEntryResponse {
  entry_id: number;
  /** patient_strings のキー（例 "fixed_rule.fever_38"） */
  notices: string[];
}

/**
 * GET entries の回答。temperature は measured のときだけ数、それ以外は null（項目は必ずある）。
 * question_text はその記録の skill_version の質問集の文（無ければ null）。
 */
export interface PatientAnswer {
  question_key: string;
  value: AnswerValue;
  temperature: number | null;
  question_text: string | null;
}

/** 自分の記録。AI の出力は含まない。 */
export interface PatientEntry {
  id: number;
  recorded_at: IsoDateTime;
  record_date: IsoDate;
  kind: EntryKind;
  by_proxy: boolean;
  /** 記録に使った質問集の版（例 "regimen-folfox@1"） */
  skill_version: string;
  answers: PatientAnswer[];
  free_text: string | null;
}

export interface PatientEntriesResponse {
  entries: PatientEntry[];
}

export interface VisitRequest {
  reception_no: string;
}

export interface VisitResponse {
  ok: boolean;
  /** patient_strings のキー（"visit.done"） */
  message_key: string;
}

// ---------------------------------------------------------------------------
// 医師 API（§8 医師）
// ---------------------------------------------------------------------------

export interface LoginRequest {
  password: string;
}

export interface DoctorPatient {
  id: string;
  regimen: Regimen;
  created_at: IsoDateTime;
  register_url: string;
}

export interface PatientsResponse {
  patients: DoctorPatient[];
}

export interface CreatePatientRequest {
  regimen: Regimen;
}

export interface CreatePatientResponse {
  id: string;
  /** {public_base_url}/register?pid=<id>。QR はフロントで描く */
  register_url: string;
}

export interface CoursesResponse {
  courses: Course[];
}

export interface VisitSummary {
  id: number;
  /** 印刷済み・期限切れで null */
  reception_no: string | null;
  patient_id: string;
  status: VisitStatus;
  fallback: boolean;
  created_at: IsoDateTime;
  expires_at: IsoDateTime;
  unprocessed_count: number;
}

export interface VisitsResponse {
  visits: VisitSummary[];
}

/** D6。原文。紙には載せない。 */
export interface UnprocessedItem {
  entry_id: number;
  record_date: IsoDate;
  /** 検出規則名（例 "unknown_before_honorific"） */
  reason: string;
  text: string;
}

export interface UnprocessedResponse {
  entries: UnprocessedItem[];
}

/** D5。文面は含まない。 */
export interface PipelineEvent {
  ts: IsoDateTime;
  event: string;
  hook_name: string | null;
  agent_type: string | null;
  tool_name: string | null;
  decision: string | null;
  duration_ms: number | null;
}

export interface PipelineEventsResponse {
  status: VisitStatus;
  events: PipelineEvent[];
}

export interface SkillInfo {
  name: string;
  version: number;
}

export interface SkillsResponse {
  skills: SkillInfo[];
}

export interface CreateSkillChangeRequest {
  skill_name: string;
  request_text: string;
}

export interface CreateSkillChangeResponse {
  id: number;
  status: SkillChangeStatus;
  /** unified diff。失敗時は null */
  diff: string | null;
}

/**
 * GET /api/doctor/skill-changes の1件。§8 は「一覧」としか書いていないので、
 * skill_changes 表（§2）の列を仮置きで写している（契約の確定待ち）。
 */
export interface SkillChange {
  id: number;
  skill_name: string;
  requested_text: string;
  diff: string | null;
  status: SkillChangeStatus;
  base_version: number;
  new_version: number | null;
  error_code: string | null;
  created_at: IsoDateTime;
  decided_at: IsoDateTime | null;
}

export interface SkillChangesResponse {
  skill_changes: SkillChange[];
}

export interface DecideSkillChangeResponse {
  ok: boolean;
  new_version?: number | null;
}
