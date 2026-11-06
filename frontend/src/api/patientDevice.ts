/**
 * スマホ保存の患者 API（docs/plan-device-records.md §5）。記録の中身は送らない。
 * 成功の本文は形を検査してから返す（違えば ApiError(200, "invalid_response")）。
 */
import { getJson, postJson, seg } from "./http";
import { PATIENT_TIMEOUT_MS } from "./patient";
import {
  isDemoConfigResponse,
  isDemoEntriesResponse,
  isOkTrue,
  isRecordMarkResponse,
  isVisitDaysResponse,
  isVisitWindowResponse,
} from "./patientGuards";
import type {
  DemoConfigResponse,
  DemoEntriesResponse,
  OkResponse,
  PatientVisitDaysResponse,
  RecordMarkResponse,
  UndoRecordMarkRequest,
  VisitWindowResponse,
} from "./types";
import { checked } from "./validate";

const OPTIONS = { timeoutMs: PATIENT_TIMEOUT_MS } as const;

/** 今日の印を付ける（本文なし）。record_date・recorded_at はサーバーの時計の値。 */
export async function addRecordMark(pid: string): Promise<RecordMarkResponse> {
  const body = await postJson(
    `/api/patient/${seg(pid)}/record-marks`,
    undefined,
    OPTIONS,
  );
  return checked(body, isRecordMarkResponse);
}

/**
 * 「つらくて書けない」の取り消し。記録から 10 分を過ぎた・その後に受付があれば
 * 409 not_undoable。何度呼んでもよい。
 */
export async function undoRecordMark(
  pid: string,
  request: UndoRecordMarkRequest,
): Promise<OkResponse> {
  const body = await postJson(
    `/api/patient/${seg(pid)}/record-marks/undo`,
    request,
    OPTIONS,
  );
  return checked(body, isOkTrue);
}

/** 受診日と受付の時刻（新しい順）。 */
export async function getVisitDays(
  pid: string,
): Promise<PatientVisitDaysResponse> {
  const body = await getJson(`/api/patient/${seg(pid)}/visit-days`, OPTIONS);
  return checked(body, isVisitDaysResponse);
}

/** 受診で送る範囲。今コースが無ければ 409 no_course。 */
export async function getVisitWindow(
  pid: string,
): Promise<VisitWindowResponse> {
  const body = await getJson(`/api/patient/${seg(pid)}/visit-window`, OPTIONS);
  return checked(body, isVisitWindowResponse);
}

/** この端末の通知の登録と Cookie を消す（通知を登録していなければ endpoint は null）。 */
export async function unregisterPatient(
  pid: string,
  endpoint: string | null,
): Promise<OkResponse> {
  const body = await postJson(
    `/api/patient/${seg(pid)}/unregister`,
    { endpoint },
    OPTIONS,
  );
  return checked(body, isOkTrue);
}

/** 撮影の見本を出すか（TSUTAE_DEMO_TOOLS=1 のデモ患者だけ true）。 */
export async function getDemoConfig(pid: string): Promise<DemoConfigResponse> {
  const body = await getJson(`/api/patient/${seg(pid)}/demo-config`, OPTIONS);
  return checked(body, isDemoConfigResponse);
}

/** 撮影の見本の記録。出せないときは 404。 */
export async function getDemoEntries(
  pid: string,
): Promise<DemoEntriesResponse> {
  const body = await getJson(`/api/patient/${seg(pid)}/demo-entries`, OPTIONS);
  return checked(body, isDemoEntriesResponse);
}
