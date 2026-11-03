/**
 * 患者 API（docs/architecture.md §8 患者）。Cookie tsutae_pid で識別される。
 * 成功の本文は形を検査してから返す（違えば ApiError(200, "invalid_response")）。
 */
import { getJson, postJson, seg } from "./http";
import {
  isCreateEntryResponse,
  isOkTrue,
  isPatientEntriesResponse,
  isQuestionsResponse,
  isVisitResponse,
} from "./patientGuards";
import type {
  CreateEntryResponse,
  EntryCreate,
  OkResponse,
  PatientEntriesResponse,
  PatientStrings,
  QuestionsResponse,
  RegisterRequest,
  VisitRequest,
  VisitResponse,
} from "./types";
import { checked } from "./validate";

export async function registerPatient(pid: string): Promise<OkResponse> {
  const body: RegisterRequest = { pid };
  return checked(await postJson("/api/patient/register", body), isOkTrue);
}

/** 本文の検査は PatientStrings.tsx の validatePatientStrings（失敗時は同梱の定型文）。 */
export function getPatientStrings(): Promise<PatientStrings> {
  return getJson<PatientStrings>("/api/patient/strings");
}

export async function getQuestions(pid: string): Promise<QuestionsResponse> {
  const body = await getJson(`/api/patient/${seg(pid)}/questions`);
  return checked(body, isQuestionsResponse);
}

export async function createEntry(
  pid: string,
  entry: EntryCreate,
): Promise<CreateEntryResponse> {
  const body = await postJson(`/api/patient/${seg(pid)}/entries`, entry);
  return checked(body, isCreateEntryResponse);
}

export async function listEntries(
  pid: string,
): Promise<PatientEntriesResponse> {
  const body = await getJson(`/api/patient/${seg(pid)}/entries`);
  return checked(body, isPatientEntriesResponse);
}

export async function submitVisit(receptionNo: string): Promise<VisitResponse> {
  const body: VisitRequest = { reception_no: receptionNo };
  return checked(await postJson("/api/visit", body), isVisitResponse);
}
