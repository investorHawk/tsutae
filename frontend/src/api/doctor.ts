/**
 * 医師 API（docs/architecture.md §8 医師）。Cookie tsutae_doctor で認証される。
 * 2xx の本文は全てここで検査し、契約と違えば ApiError(200, "invalid_response") を投げる
 * （§9 W2b の決定。{ok:false} を成功として扱わない）。
 */
import {
  isApproveResponse,
  isCoursesResponse,
  isCreatePatientResponse,
  isCreateSkillChangeResponse,
  isOkTrue,
  isPatientsResponse,
  isPipelineEventsResponse,
  isSavedCourse,
  isSkillChangesResponse,
  isSkillsResponse,
  isUnprocessedResponse,
  isVisitsResponse,
} from "./doctorGuards";
import { getJson, isApiError, postJson, seg } from "./http";
import type {
  ApproveSkillChangeResponse,
  CoursesResponse,
  Course,
  CreatePatientRequest,
  CreatePatientResponse,
  CreateSkillChangeRequest,
  CreateSkillChangeResponse,
  LoginRequest,
  OkResponse,
  PatientsResponse,
  PipelineEventsResponse,
  Regimen,
  RejectSkillChangeResponse,
  SkillChangesResponse,
  SkillsResponse,
  UnprocessedResponse,
  VisitsResponse,
} from "./types";
import { type Item, checked } from "./validate";

type Guard = (body: Item) => boolean;

/** 医師 API の打ち切り（ms）。打ち切りは通信の失敗（network_error）と同じ扱い。 */
export const DOCTOR_TIMEOUT_MS = 30_000;
/**
 * D4 の書き換えの依頼の打ち切り（ms）。サーバーは editor を pipeline_timeout_s
 * （既定 600 秒）で打ち切るので、それに合わせて 10 分待つ。
 */
export const SKILL_CHANGE_TIMEOUT_MS = 10 * 60 * 1000;

async function getChecked<T>(path: string, isBody: Guard): Promise<T> {
  return checked<T>(
    await getJson<unknown>(path, { timeoutMs: DOCTOR_TIMEOUT_MS }),
    isBody,
  );
}

async function postChecked<T>(
  path: string,
  isBody: Guard,
  body?: unknown,
  timeoutMs: number = DOCTOR_TIMEOUT_MS,
): Promise<T> {
  return checked<T>(await postJson<unknown>(path, body, { timeoutMs }), isBody);
}

// --- ログイン -------------------------------------------------------------

export function login(password: string): Promise<OkResponse> {
  const body: LoginRequest = { password };
  return postChecked<OkResponse>("/api/doctor/login", isOkTrue, body);
}

export function logout(): Promise<OkResponse> {
  return postChecked<OkResponse>("/api/doctor/logout", isOkTrue);
}

/**
 * ログイン済みかを確かめる。§8 に専用の経路が無いので、軽い GET（Skill 一覧）の
 * 401 で判断する。401 以外の失敗（壊れた 2xx の invalid_response を含む）はそのまま投げる。
 */
export async function checkDoctorSession(): Promise<boolean> {
  try {
    await listSkills();
    return true;
  } catch (err) {
    if (isApiError(err) && err.isUnauthorized) {
      return false;
    }
    throw err;
  }
}

// --- 患者・コース（D1, D2） ------------------------------------------------

export function listPatients(): Promise<PatientsResponse> {
  return getChecked<PatientsResponse>(
    "/api/doctor/patients",
    isPatientsResponse,
  );
}

export function createPatient(
  regimen: Regimen,
): Promise<CreatePatientResponse> {
  const body: CreatePatientRequest = { regimen };
  return postChecked<CreatePatientResponse>(
    "/api/doctor/patients",
    isCreatePatientResponse,
    body,
  );
}

export function listCourses(pid: string): Promise<CoursesResponse> {
  return getChecked<CoursesResponse>(
    `/api/doctor/patients/${seg(pid)}/courses`,
    isCoursesResponse,
  );
}

/** 実投与日の登録。矛盾は 400 {"error": code}。 */
export function saveCourse(course: Course): Promise<Course> {
  return postChecked<Course>(
    "/api/doctor/courses",
    isSavedCourse(course),
    course,
  );
}

// --- 受診（D3, D5, D6） ----------------------------------------------------

export function listVisits(): Promise<VisitsResponse> {
  return getChecked<VisitsResponse>("/api/doctor/visits", isVisitsResponse);
}

/** レポート（text/html、A4 印刷用）の URL。新しいタブや iframe で開く。 */
export function reportUrl(visitId: number): string {
  return `/api/doctor/visits/${seg(visitId)}/report`;
}

/** 印刷済み。レポート・変換結果・受付番号がサーバーから消える。 */
export function markPrinted(visitId: number): Promise<OkResponse> {
  return postChecked<OkResponse>(
    `/api/doctor/visits/${seg(visitId)}/printed`,
    isOkTrue,
  );
}

/**
 * AI でもう一度変換（failed・AI変換なしの ready だけ）。受け付けたら generating に
 * なり、変換はサーバーのバックグラウンドで動く（結果は一覧の取り直しで見る）。
 * 生成中・AI の結果あり・印刷済み・期限切れは 409 {"error":"not_regenerable"}。
 */
export function regenerateVisit(visitId: number): Promise<OkResponse> {
  return postChecked<OkResponse>(
    `/api/doctor/visits/${seg(visitId)}/regenerate`,
    isOkTrue,
  );
}

export function listUnprocessed(visitId: number): Promise<UnprocessedResponse> {
  return getChecked<UnprocessedResponse>(
    `/api/doctor/visits/${seg(visitId)}/unprocessed`,
    isUnprocessedResponse,
  );
}

export function getPipelineEvents(
  visitId: number,
): Promise<PipelineEventsResponse> {
  return getChecked<PipelineEventsResponse>(
    `/api/doctor/pipeline/${seg(visitId)}/events`,
    isPipelineEventsResponse,
  );
}

// --- Skill の書き換え（D4） ------------------------------------------------

export function listSkills(): Promise<SkillsResponse> {
  return getChecked<SkillsResponse>("/api/doctor/skills", isSkillsResponse);
}

export function createSkillChange(
  skillName: string,
  requestText: string,
): Promise<CreateSkillChangeResponse> {
  const body: CreateSkillChangeRequest = {
    skill_name: skillName,
    request_text: requestText,
  };
  return postChecked<CreateSkillChangeResponse>(
    "/api/doctor/skill-changes",
    isCreateSkillChangeResponse,
    body,
    SKILL_CHANGE_TIMEOUT_MS,
  );
}

export function listSkillChanges(): Promise<SkillChangesResponse> {
  return getChecked<SkillChangesResponse>(
    "/api/doctor/skill-changes",
    isSkillChangesResponse,
  );
}

/**
 * 承認。応答の new_version（上がった後の version）は必須。Skill のロックを別の承認・
 * 却下が握っていれば 409 {"error":"busy"}（変更は pending のまま。やり直せる）。
 */
export function approveSkillChange(
  id: number,
): Promise<ApproveSkillChangeResponse> {
  return postChecked<ApproveSkillChangeResponse>(
    `/api/doctor/skill-changes/${seg(id)}/approve`,
    isApproveResponse,
  );
}

/** 却下。応答は {ok: true} だけ。承認と同じく 409 busy がありうる。 */
export function rejectSkillChange(
  id: number,
): Promise<RejectSkillChangeResponse> {
  return postChecked<RejectSkillChangeResponse>(
    `/api/doctor/skill-changes/${seg(id)}/reject`,
    isOkTrue,
  );
}
