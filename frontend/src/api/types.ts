/**
 * API に出る型。backend/tsutae/schemas.py（pydantic）と docs/architecture.md §8 を写したもの。
 * 日付は "YYYY-MM-DD"、日時は ISO 8601（+09:00 付き）の文字列。
 */

export type IsoDate = string;
export type IsoDateTime = string;

// ---------------------------------------------------------------------------
// 基本の列挙（schemas.py）
// ---------------------------------------------------------------------------

/**
 * レジメンの識別名（v1.1。FOLFOX/CAPOX に固定しない。英大文字・数字・`-`、30字まで）。
 * 選べる一覧は GET /api/doctor/regimens（D4 で採用したレジメンも入る）。
 */
export type Regimen = string;
export type ThreeLevel = "none" | "present" | "hard";
export type FeverValue = "not_measured" | "measured";
export type AnswerValue = ThreeLevel | FeverValue;
export type AnswerType = "three_level" | "temperature";
export type EntryKind = "too_sick" | "answers" | "free_text" | "mixed";
export type VisitStatus = "generating" | "ready" | "printed" | "failed";
/** 印刷待ち一覧（GET visits）に出る状態。印刷済み・期限切れは一覧に出ない。 */
export type OpenVisitStatus = Exclude<VisitStatus, "printed">;
export type SkillChangeStatus = "pending" | "approved" | "rejected" | "failed";

/** 識別名の書式（schemas.py の REGIMEN_CODE_PATTERN・REGIMEN_CODE_MAX と同じ）。 */
export const REGIMEN_CODE_PATTERN = /^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$/;
export const REGIMEN_CODE_MAX = 30;
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
  /** サーバーの今日（JST の YYYY-MM-DD。今日の記録の見出しの日付） */
  today: string;
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

/**
 * 自分の受診日（受付のあった日。状態を問わない）。返るのは日付と、その日の最初の受付の
 * 時刻だけ（受付番号・状態・レポートは無い）。これまでの記録の区切りに使う。
 */
export interface PatientVisitDay {
  visit_date: IsoDate;
  received_at: IsoDateTime;
}

export interface PatientEntriesResponse {
  entries: PatientEntry[];
  /** 新しい順 */
  visits: PatientVisitDay[];
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

/**
 * 患者一覧の1件。last_record_date・current_course_no・next_visit は無ければ null
 * （項目は必ずある）。今のコースは今日（サーバーの config.today()）で決め、次回受診は
 * 今のコースの次回受診予定日。current_day は今日の今のコースでの Day、
 * days_since_last_record は今日 − 最後の記録日（記録が無ければ null）、record_stale は
 * 最後の記録が3日以上前か記録が無い（判定はサーバー）。
 */
export interface DoctorPatient {
  id: string;
  regimen: Regimen;
  created_at: IsoDateTime;
  register_url: string;
  last_record_date: IsoDate | null;
  days_since_last_record: number | null;
  record_stale: boolean;
  current_course_no: number | null;
  current_day: number | null;
  next_visit: IsoDate | null;
}

export interface PatientsResponse {
  patients: DoctorPatient[];
}

export interface CreatePatientRequest {
  regimen: Regimen;
}

/**
 * GET regimens の1件（置かれていて検査に通るレジメン。T95）。
 * skill_name は `regimen-` + 識別名の小文字、display_name は紙のヘッダ・画面の名前
 * （SKILL.md の display_name、無ければ識別名）。並びは FOLFOX・CAPOX が先。
 */
export interface RegimenChoice {
  code: Regimen;
  skill_name: string;
  version: number;
  display_name: string;
}

export interface RegimensResponse {
  regimens: RegimenChoice[];
}

export interface CreatePatientResponse {
  id: string;
  /** {public_base_url}/register?pid=<id>。QR はフロントで描く */
  register_url: string;
}

export interface CoursesResponse {
  courses: Course[];
}

/**
 * 患者の画面（D2）の受診1件（新しい順）。印刷済み・期限切れも出る（受付番号は null）。
 * report_available はレポートを開ける（受付番号が残っている ready）とき true。
 */
export interface PatientVisit {
  id: number;
  reception_no: string | null;
  visit_date: IsoDate;
  created_at: IsoDateTime;
  status: VisitStatus;
  fallback: boolean;
  report_available: boolean;
  unprocessed_count: number;
}

export interface PatientVisitsResponse {
  visits: PatientVisit[];
}

/**
 * 患者の画面の記録のクローズ回答（コードのまま。表示名は画面で引く）。
 * question_label はその記録の版の form の短い名前（D4 で足した質問の名前に使う。既知の
 * 6問は画面の表が先。form の無い版は null。v1.1）。
 */
export interface DoctorEntryAnswer {
  question_key: string;
  value: AnswerValue;
  temperature: number | null;
  question_label: string | null;
}

/**
 * 患者の画面の記録1件。自由記載は有無だけ（原文は D6 だけに出る）。
 * course_no・day は記録日のコースと Day（サーバーで計算。コース外・矛盾は null）。
 */
export interface DoctorEntry {
  id: number;
  recorded_at: IsoDateTime;
  record_date: IsoDate;
  course_no: number | null;
  day: number | null;
  kind: EntryKind;
  by_proxy: boolean;
  answers: DoctorEntryAnswer[];
  has_free_text: boolean;
}

/** 直近の記録（新しい順、上限あり）と、その患者の記録の総数。 */
export interface PatientEntriesSummaryResponse {
  entries: DoctorEntry[];
  total: number;
}

/**
 * 印刷待ち一覧の1件（W3 後の決定）。出るのは受付番号のある generating・ready・failed だけ
 * （印刷済み・期限切れは一覧から消える）。
 */
export interface VisitSummary {
  id: number;
  reception_no: string;
  patient_id: string;
  status: OpenVisitStatus;
  fallback: boolean;
  created_at: IsoDateTime;
  expires_at: IsoDateTime;
  unprocessed_count: number;
}

export interface VisitsResponse {
  visits: VisitSummary[];
}

/**
 * 未処理・変換ログの見出しの受診。受付番号は印刷済み・期限切れで null。
 * report_available はレポートを開ける（受付番号が残っていて期限内の ready）とき true。
 */
export interface VisitHeader {
  id: number;
  reception_no: string | null;
  patient_id: string;
  visit_date: IsoDate;
  /** 受付の時刻 */
  created_at: IsoDateTime;
  status: VisitStatus;
  fallback: boolean;
  report_available: boolean;
}

/** D6。原文。紙には載せない。course_no・day は記録日のコースと Day（無ければ null）。 */
export interface UnprocessedItem {
  entry_id: number;
  record_date: IsoDate;
  course_no: number | null;
  day: number | null;
  /** 検出規則名（例 "unknown_before_honorific"） */
  reason: string;
  text: string;
  /** 疑われた語の text の中の位置（code point の [start, end)。位置順・重なりなし） */
  marks: TextMark[];
  /** 保存済みの医師の伏せ字（無ければ null）。区間は text の位置 */
  doctor_mask: DoctorMaskView | null;
}

/** 医師の伏せ字（D6）。spans は原文（text）の伏せる区間、confirmed_clear は確かめた印。 */
export interface DoctorMaskView {
  spans: TextMark[];
  confirmed_clear: boolean;
}

/** POST /visits/{id}/masks/check の本文（医師は文を書かない。区間だけを送る）。 */
export interface MaskCheckRequest {
  entry_id: number;
  spans: TextMark[];
}

/** まだ疑われる区間（masked_text の code point の位置）と規則名。 */
export interface MaskSuspect extends TextMark {
  rule: string;
}

/** 区間を当てた後の、送られる文とまだ疑われる区間。保存はしない。 */
export interface MaskCheckResponse {
  entry_id: number;
  masked_text: string;
  suspects: MaskSuspect[];
  /** 送れない理由の規則名（無ければ null = そのまま送れる） */
  reason: string | null;
  sendable: boolean;
  /** 「個人を特定する語は無いことを確かめた」で送れる */
  confirmable: boolean;
}

export interface MaskSaveEntry {
  entry_id: number;
  /** false なら未処理のまま（保存済みの伏せ字も消す） */
  send: boolean;
  spans: TextMark[];
  confirmed_clear: boolean;
}

export interface MaskSaveRequest {
  entries: MaskSaveEntry[];
}

/** 保存の応答。sendable は保存した記録のうち変換で送られる件数。 */
export interface MaskSaveResponse {
  ok: true;
  sendable: number;
}

export interface TextMark {
  start: number;
  end: number;
}

export interface UnprocessedResponse {
  visit: VisitHeader;
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
  visit: VisitHeader;
  events: PipelineEvent[];
}

export interface SkillInfo {
  name: string;
  version: number;
}

/**
 * 読めない Skill（壊れた SKILL.md・欠けた必須 Skill）。一覧から黙って落とさず、
 * 設定画面に出す（W3 後の決定。§8 の表は code と書くが、API の項目名は error_code）。
 */
export interface InvalidSkill {
  name: string;
  /** 例 "format"・"schema"・"missing" */
  error_code: string;
  /** regimen の2本と report-format-default */
  required: boolean;
}

export interface SkillsResponse {
  skills: SkillInfo[];
  invalid: InvalidSkill[];
}

/**
 * GET /api/doctor/skills/{name}: 1つの Skill の今の中身（設定画面で依頼の前に見せる。
 * 読み取り専用）。questions は regimen の質問（report-format は空）、text は SKILL.md の全文。
 */
export interface SkillContentResponse {
  name: string;
  version: number;
  description: string;
  questions: Question[];
  text: string;
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

/** GET /api/doctor/skill-changes の1件（new_text は返さない。差分で足りる）。 */
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

/** POST approve の応答。new_version（上がった後の version）は必須。 */
export interface ApproveSkillChangeResponse {
  ok: true;
  new_version: number;
}

/** POST reject の応答（{ok: true} だけ）。 */
export interface RejectSkillChangeResponse {
  ok: true;
}

/** 質問の部品集の出どころ（初期の6問・医師が足した・採用したレジメンから）。 */
export type QuestionOrigin = "seed" | "doctor" | "adopted";

/** 質問の部品集の1問（D4 レジメンの小窓の候補。v1.1）。 */
export interface LibraryQuestion {
  key: string;
  /** 医師画面の短い名前（例: しびれ） */
  label: string;
  text: string;
  answer_type: AnswerType;
  origin: QuestionOrigin;
}

/** GET /api/doctor/question-library（外した問は含まない。初期の6問が先）。 */
export interface QuestionLibraryResponse {
  questions: LibraryQuestion[];
}

/**
 * POST /api/doctor/question-library。回答の型は3択だけ（体温は初期の fever だけ）。
 * 形・H1 に掛かれば 422 {error, field}、key の重複（外した key も）は 409 key_taken。
 */
export interface AddLibraryQuestionRequest {
  key: string;
  label: string;
  text: string;
  answer_type?: "three_level";
}

export interface AddLibraryQuestionResponse {
  question: LibraryQuestion;
}
