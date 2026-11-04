import { afterEach, describe, expect, it } from "vitest";
import { callOf, jsonResponse, mockFetch } from "../test/fetchMock";
import { ApiError } from "./http";
import {
  createEntry,
  getPatientStrings,
  getQuestions,
  listEntries,
  registerPatient,
  submitVisit,
} from "./patient";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("患者 API", () => {
  it("registerPatient: POST /api/patient/register {pid}", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    await expect(registerPatient("P-DEMO0001")).resolves.toEqual({ ok: true });
    const call = callOf(fetchMock);
    expect(call.method).toBe("POST");
    expect(call.url).toBe("/api/patient/register");
    expect(call.body).toEqual({ pid: "P-DEMO0001" });
  });

  it("registerPatient: 未知の pid は ApiError(404, unknown_patient)", async () => {
    mockFetch(() => jsonResponse({ error: "unknown_patient" }, 404));
    const err = await registerPatient("P-ZZZZ9999").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("unknown_patient");
    expect((err as ApiError).status).toBe(404);
  });

  it("getPatientStrings: GET /api/patient/strings", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ "app.title": "つたえ" }));
    await expect(getPatientStrings()).resolves.toEqual({
      "app.title": "つたえ",
    });
    const call = callOf(fetchMock);
    expect(call.method).toBe("GET");
    expect(call.url).toBe("/api/patient/strings");
  });

  it("getQuestions: GET /api/patient/{pid}/questions", async () => {
    const body = {
      skill_version: "regimen-folfox@1",
      questions: [
        {
          key: "diarrhea",
          text: "下痢はありましたか",
          answer_type: "three_level",
        },
      ],
      today: "2026-11-09",
    };
    const fetchMock = mockFetch(() => jsonResponse(body));
    await expect(getQuestions("P-DEMO0001")).resolves.toEqual(body);
    const call = callOf(fetchMock);
    expect(call.method).toBe("GET");
    expect(call.url).toBe("/api/patient/P-DEMO0001/questions");
  });

  it("createEntry: POST /api/patient/{pid}/entries に EntryCreate", async () => {
    const fetchMock = mockFetch(() =>
      jsonResponse({ entry_id: 7, notices: ["fixed_rule.fever_38"] }),
    );
    const entry = {
      by_proxy: true,
      answers: [
        { question_key: "diarrhea", value: "present" as const },
        {
          question_key: "fever",
          value: "measured" as const,
          temperature: 38.2,
        },
      ],
      free_text: "点滴の次の日からおなかがゆるい",
    };
    await expect(createEntry("P-DEMO0001", entry)).resolves.toEqual({
      entry_id: 7,
      notices: ["fixed_rule.fever_38"],
    });
    const call = callOf(fetchMock);
    expect(call.method).toBe("POST");
    expect(call.url).toBe("/api/patient/P-DEMO0001/entries");
    expect(call.body).toEqual(entry);
  });

  it("createEntry: つらくて書けない", async () => {
    const fetchMock = mockFetch(() =>
      jsonResponse({ entry_id: 8, notices: [] }),
    );
    await createEntry("P-DEMO0001", { too_sick: true });
    expect(callOf(fetchMock).body).toEqual({ too_sick: true });
  });

  it("listEntries: GET /api/patient/{pid}/entries", async () => {
    const body = {
      entries: [
        {
          id: 1,
          recorded_at: "2026-11-01T20:00:00+09:00",
          record_date: "2026-11-01",
          kind: "too_sick",
          by_proxy: false,
          skill_version: "regimen-folfox@1",
          answers: [],
          free_text: null,
        },
      ],
      visits: [
        {
          visit_date: "2026-11-09",
          received_at: "2026-11-09T09:40:00+09:00",
        },
      ],
    };
    const fetchMock = mockFetch(() => jsonResponse(body));
    await expect(listEntries("P-DEMO0001")).resolves.toEqual(body);
    const call = callOf(fetchMock);
    expect(call.method).toBe("GET");
    expect(call.url).toBe("/api/patient/P-DEMO0001/entries");
  });

  it("submitVisit: POST /api/visit {reception_no}", async () => {
    const fetchMock = mockFetch(() =>
      jsonResponse({ ok: true, message_key: "visit.done" }),
    );
    await expect(submitVisit("A-023")).resolves.toEqual({
      ok: true,
      message_key: "visit.done",
    });
    const call = callOf(fetchMock);
    expect(call.method).toBe("POST");
    expect(call.url).toBe("/api/visit");
    expect(call.body).toEqual({ reception_no: "A-023" });
  });

  it("pid は経路用にエンコードする", async () => {
    const fetchMock = mockFetch(() =>
      jsonResponse({ entries: [], visits: [] }),
    );
    await listEntries("../doctor/x");
    expect(callOf(fetchMock).url).toBe("/api/patient/..%2Fdoctor%2Fx/entries");
  });
});
