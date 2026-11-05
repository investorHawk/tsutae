import { afterEach, describe, expect, it } from "vitest";
import { callOf, jsonResponse, mockFetch } from "../test/fetchMock";
import { ApiError } from "./http";
import {
  getPatientStrings,
  getQuestions,
  registerPatient,
  submitVisit,
} from "./patient";
import { addRecordMark, getVisitDays, undoRecordMark } from "./patientDevice";

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
      fixed_rules: [
        {
          question_key: "fever",
          threshold_celsius: 38,
          patient_string_key: "fixed_rule.fever_38",
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

  it("addRecordMark: POST /api/patient/{pid}/record-marks（本文なし）", async () => {
    const body = {
      record_date: "2026-11-09",
      recorded_at: "2026-11-09T20:00:00.000000+09:00",
    };
    const fetchMock = mockFetch(() => jsonResponse(body));
    await expect(addRecordMark("P-DEMO0001")).resolves.toEqual(body);
    const call = callOf(fetchMock);
    expect(call.method).toBe("POST");
    expect(call.url).toBe("/api/patient/P-DEMO0001/record-marks");
    expect(call.body).toBeUndefined();
  });

  it("undoRecordMark: POST /api/patient/{pid}/record-marks/undo", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    const request = {
      recorded_at: "2026-11-09T20:00:00.000000+09:00",
      clear_mark: true,
    };
    await expect(undoRecordMark("P-DEMO0001", request)).resolves.toEqual({
      ok: true,
    });
    const call = callOf(fetchMock);
    expect(call.method).toBe("POST");
    expect(call.url).toBe("/api/patient/P-DEMO0001/record-marks/undo");
    expect(call.body).toEqual(request);
  });

  it("getVisitDays: GET /api/patient/{pid}/visit-days", async () => {
    const body = {
      visits: [
        {
          visit_date: "2026-11-09",
          received_at: "2026-11-09T09:40:00+09:00",
        },
      ],
    };
    const fetchMock = mockFetch(() => jsonResponse(body));
    await expect(getVisitDays("P-DEMO0001")).resolves.toEqual(body);
    const call = callOf(fetchMock);
    expect(call.method).toBe("GET");
    expect(call.url).toBe("/api/patient/P-DEMO0001/visit-days");
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

  it("submitVisit: 記録があれば本文に entries を入れる", async () => {
    const fetchMock = mockFetch(() =>
      jsonResponse({ ok: true, message_key: "visit.done" }),
    );
    await submitVisit("A-023", []);
    expect(callOf(fetchMock).body).toEqual({
      reception_no: "A-023",
      entries: [],
    });
  });

  it("pid は経路用にエンコードする", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ visits: [] }));
    await getVisitDays("../doctor/x");
    expect(callOf(fetchMock).url).toBe(
      "/api/patient/..%2Fdoctor%2Fx/visit-days",
    );
  });
});
