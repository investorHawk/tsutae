/** 患者 API の偽物。経路とメソッドで応答を選ぶ。 */
import {
  jsonResponse,
  mockFetch,
  type FetchMock,
} from "../../../test/fetchMock";
import { ENTRIES, PID, QUESTIONS_RESPONSE, entriesBody } from "./fixtures";

export type Reply = Response | Promise<Response>;

export interface PatientApiReplies {
  questions?: () => Reply;
  createEntry?: (body: unknown) => Reply;
  entries?: () => Reply;
  /** POST entries/{id}/undo（取り消し）。引数は経路の id */
  undo?: (entryId: number) => Reply;
  visit?: (body: unknown) => Reply;
  /** POST /api/patient/register（番号の手入力） */
  register?: (body: unknown) => Reply;
}

const DEFAULTS: Required<PatientApiReplies> = {
  questions: () => jsonResponse(QUESTIONS_RESPONSE),
  createEntry: () => jsonResponse({ entry_id: 1, notices: [] }),
  entries: () => jsonResponse(entriesBody(ENTRIES)),
  undo: () => jsonResponse({ ok: true }),
  visit: () => jsonResponse({ ok: true, message_key: "visit.done" }),
  register: () => jsonResponse({ ok: true }),
};

function bodyOf(init?: RequestInit): unknown {
  return typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
}

export function mockPatientApi(replies: PatientApiReplies = {}): FetchMock {
  const r = { ...DEFAULTS, ...replies };
  const base = `/api/patient/${PID}`;
  return mockFetch((url, init) => {
    const method = init?.method ?? "GET";
    if (method === "GET" && url === `${base}/questions`) {
      return r.questions();
    }
    if (method === "POST" && url === `${base}/entries`) {
      return r.createEntry(bodyOf(init));
    }
    if (method === "GET" && url === `${base}/entries`) {
      return r.entries();
    }
    const undo = /^\/entries\/(\d+)\/undo$/.exec(url.slice(base.length));
    if (method === "POST" && url.startsWith(base) && undo) {
      return r.undo(Number(undo[1]));
    }
    if (method === "POST" && url === "/api/visit") {
      return r.visit(bodyOf(init));
    }
    if (method === "POST" && url === "/api/patient/register") {
      return r.register(bodyOf(init));
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
