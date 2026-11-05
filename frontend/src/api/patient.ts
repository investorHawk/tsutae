/**
 * 患者 API（docs/architecture.md §8 患者）。Cookie tsutae_pid で識別される。
 * 成功の本文は形を検査してから返す（違えば ApiError(200, "invalid_response")）。
 */
import { getJson, postJson, seg } from "./http";
import {
  isOkTrue,
  isQuestionsResponse,
  isVisitResponse,
} from "./patientGuards";
import type {
  OkResponse,
  PatientStrings,
  QuestionsResponse,
  RegisterRequest,
  VisitEntry,
  VisitRequest,
  VisitResponse,
} from "./types";
import { checked } from "./validate";

/** 患者 API の打ち切り（ms）。打ち切りは通信の失敗と同じ扱い（画面は error.generic）。 */
export const PATIENT_TIMEOUT_MS = 20_000;
const OPTIONS = { timeoutMs: PATIENT_TIMEOUT_MS } as const;

export async function registerPatient(pid: string): Promise<OkResponse> {
  const body: RegisterRequest = { pid };
  return checked(
    await postJson("/api/patient/register", body, OPTIONS),
    isOkTrue,
  );
}

/** 本文の検査は PatientStrings.tsx の validatePatientStrings（失敗時は同梱の定型文）。 */
export function getPatientStrings(): Promise<PatientStrings> {
  return getJson<PatientStrings>("/api/patient/strings", OPTIONS);
}

export async function getQuestions(pid: string): Promise<QuestionsResponse> {
  const body = await getJson(`/api/patient/${seg(pid)}/questions`, OPTIONS);
  return checked(body, isQuestionsResponse);
}

/**
 * 受付（POST /api/visit）。entries はスマホに置いた記録（§5.5）。無ければ本文に入れない。
 */
export async function submitVisit(
  receptionNo: string,
  entries?: readonly VisitEntry[],
): Promise<VisitResponse> {
  const body: VisitRequest = {
    reception_no: receptionNo,
    ...(entries === undefined ? {} : { entries: [...entries] }),
  };
  return checked(await postJson("/api/visit", body, OPTIONS), isVisitResponse);
}
