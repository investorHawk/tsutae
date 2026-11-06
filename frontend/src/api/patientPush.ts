/**
 * 通知の患者 API（docs/plan-device-records.md §4.3）。
 * endpoint は本文で送る（URL に入れるとアクセスログに残る）。
 * 成功の本文は形を検査してから返す（違えば ApiError(200, "invalid_response")）。
 */
import { deleteJsonBody, getJson, postJson, putJson, seg } from "./http";
import { PATIENT_TIMEOUT_MS } from "./patient";
import {
  isOkTrue,
  isPushConfigResponse,
  isPushSubscriptionResponse,
} from "./patientGuards";
import type { OkResponse } from "./types";
import { checked } from "./validate";

const OPTIONS = { timeoutMs: PATIENT_TIMEOUT_MS } as const;

export interface PushConfigResponse {
  available: boolean;
  public_key: string | null;
}

export interface PushSubscriptionRequest {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  /** JST の HH:MM（30 分刻み）。 */
  notify_time: string;
}

export interface PushSubscriptionResponse {
  ok: true;
  notify_time: string;
}

export async function getPushConfig(): Promise<PushConfigResponse> {
  const body = await getJson("/api/patient/push-config", OPTIONS);
  return checked(body, isPushConfigResponse);
}

export async function putPushSubscription(
  pid: string,
  subscription: PushSubscriptionRequest,
): Promise<PushSubscriptionResponse> {
  const body = await putJson(
    `/api/patient/${seg(pid)}/push-subscription`,
    subscription,
    OPTIONS,
  );
  return checked(body, isPushSubscriptionResponse);
}

export async function deletePushSubscription(
  pid: string,
  endpoint: string,
): Promise<OkResponse> {
  const body = await deleteJsonBody(
    `/api/patient/${seg(pid)}/push-subscription`,
    { endpoint },
    OPTIONS,
  );
  return checked(body, isOkTrue);
}

/** 試しに送る（10 秒後に1回）。登録ごとに1分に1回まで（超えたら 429 push_test_too_soon）。 */
export async function sendPushTest(
  pid: string,
  endpoint: string,
): Promise<OkResponse> {
  const body = await postJson(
    `/api/patient/${seg(pid)}/push-test`,
    { endpoint },
    OPTIONS,
  );
  return checked(body, isOkTrue);
}
