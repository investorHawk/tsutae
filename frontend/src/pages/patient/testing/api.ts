/** 患者 API の偽物。経路とメソッドで応答を選ぶ。 */
import {
  jsonResponse,
  mockFetch,
  type FetchMock,
} from "../../../test/fetchMock";
import { apiFixture } from "../../../test/apiFixtures";
import { PID, QUESTIONS_RESPONSE, STRINGS } from "./fixtures";

export type Reply = Response | Promise<Response>;

/** POST record-marks の応答（サーバーの今日の時刻）。 */
export const MARK = {
  record_date: "2026-11-09",
  recorded_at: "2026-11-09T20:00:00.000000+09:00",
};

export interface PatientApiReplies {
  /** GET strings（外枠の PatientLayout が読む） */
  strings?: () => Reply;
  questions?: () => Reply;
  /** POST record-marks（本文なし） */
  recordMark?: () => Reply;
  /** POST record-marks/undo（取り消し） */
  undo?: (body: unknown) => Reply;
  /** GET visit-days */
  visitDays?: () => Reply;
  visit?: (body: unknown) => Reply;
  /** POST /api/patient/register（番号の手入力） */
  register?: (body: unknown) => Reply;
  /** GET push-config */
  pushConfig?: () => Reply;
  /** PUT push-subscription */
  pushSubscribe?: (body: unknown) => Reply;
  /** DELETE push-subscription */
  pushUnsubscribe?: (body: unknown) => Reply;
  /** POST push-test */
  pushTest?: (body: unknown) => Reply;
}

const DEFAULTS: Required<PatientApiReplies> = {
  strings: () => jsonResponse(STRINGS),
  questions: () => jsonResponse(QUESTIONS_RESPONSE),
  recordMark: () => jsonResponse(MARK),
  undo: () => jsonResponse({ ok: true }),
  visitDays: () => jsonResponse({ visits: [] }),
  visit: () => jsonResponse({ ok: true, message_key: "visit.done" }),
  register: () => jsonResponse({ ok: true }),
  pushConfig: () => jsonResponse(apiFixture("patient_push_config").body),
  pushSubscribe: (body) =>
    jsonResponse({
      ok: true,
      notify_time: (body as { notify_time: string }).notify_time,
    }),
  pushUnsubscribe: () => jsonResponse({ ok: true }),
  pushTest: () => jsonResponse({ ok: true }),
};

function bodyOf(init?: RequestInit): unknown {
  return typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
}

export function mockPatientApi(replies: PatientApiReplies = {}): FetchMock {
  const r = { ...DEFAULTS, ...replies };
  const base = `/api/patient/${PID}`;
  return mockFetch((url, init) => {
    const method = init?.method ?? "GET";
    if (method === "GET" && url === "/api/patient/strings") {
      return r.strings();
    }
    if (method === "GET" && url === `${base}/questions`) {
      return r.questions();
    }
    if (method === "POST" && url === `${base}/record-marks`) {
      return r.recordMark();
    }
    if (method === "POST" && url === `${base}/record-marks/undo`) {
      return r.undo(bodyOf(init));
    }
    if (method === "GET" && url === `${base}/visit-days`) {
      return r.visitDays();
    }
    if (method === "POST" && url === "/api/visit") {
      return r.visit(bodyOf(init));
    }
    if (method === "POST" && url === "/api/patient/register") {
      return r.register(bodyOf(init));
    }
    if (method === "GET" && url === "/api/patient/push-config") {
      return r.pushConfig();
    }
    if (method === "PUT" && url === `${base}/push-subscription`) {
      return r.pushSubscribe(bodyOf(init));
    }
    if (method === "DELETE" && url === `${base}/push-subscription`) {
      return r.pushUnsubscribe(bodyOf(init));
    }
    if (method === "POST" && url === `${base}/push-test`) {
      return r.pushTest(bodyOf(init));
    }
    return jsonResponse({ error: "not_found" }, 404);
  });
}

/** fetch の呼び出しのうち、メソッドと経路が一致するもの。 */
export function callsTo(
  mock: FetchMock,
  method: string,
  url: string,
): unknown[] {
  return mock.mock.calls
    .filter(
      ([input, init]) =>
        String(input) === url && (init?.method ?? "GET") === method,
    )
    .map(([, init]) => bodyOf(init));
}
