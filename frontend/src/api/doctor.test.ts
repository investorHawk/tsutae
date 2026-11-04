import { afterEach, describe, expect, it } from "vitest";
import { callOf, jsonResponse, mockFetch } from "../test/fetchMock";
import { visitHeaderStub } from "../test/doctorStubs";
import { ApiError } from "./http";
import {
  approveSkillChange,
  checkDoctorSession,
  createPatient,
  createSkillChange,
  getPipelineEvents,
  listCourses,
  listPatients,
  listSkillChanges,
  listSkills,
  listUnprocessed,
  listVisits,
  login,
  logout,
  markPrinted,
  regenerateVisit,
  rejectSkillChange,
  reportUrl,
  saveCourse,
} from "./doctor";

afterEach(() => {
  vi.unstubAllGlobals();
});

type Case = {
  name: string;
  run: () => Promise<unknown>;
  method: "GET" | "POST";
  url: string;
  body?: unknown;
  response: unknown;
};

const course = {
  patient_id: "P-DEMO0001",
  course_no: 2,
  infusion_date: "2026-10-13",
  planned_date: "2026-10-11",
  next_visit: null,
  note: null,
};

const cases: Case[] = [
  {
    name: "login",
    run: () => login("demo-pass"),
    method: "POST",
    url: "/api/doctor/login",
    body: { password: "demo-pass" },
    response: { ok: true },
  },
  {
    name: "logout",
    run: () => logout(),
    method: "POST",
    url: "/api/doctor/logout",
    response: { ok: true },
  },
  {
    name: "listPatients",
    run: () => listPatients(),
    method: "GET",
    url: "/api/doctor/patients",
    response: { patients: [] },
  },
  {
    name: "createPatient",
    run: () => createPatient("FOLFOX"),
    method: "POST",
    url: "/api/doctor/patients",
    body: { regimen: "FOLFOX" },
    response: {
      id: "P-AB12CD34",
      register_url: "http://localhost:5173/register?pid=P-AB12CD34",
    },
  },
  {
    name: "listCourses",
    run: () => listCourses("P-DEMO0001"),
    method: "GET",
    url: "/api/doctor/patients/P-DEMO0001/courses",
    response: { courses: [course] },
  },
  {
    name: "saveCourse",
    run: () => saveCourse(course),
    method: "POST",
    url: "/api/doctor/courses",
    body: course,
    response: { ...course, id: 2 },
  },
  {
    name: "listVisits",
    run: () => listVisits(),
    method: "GET",
    url: "/api/doctor/visits",
    response: { visits: [] },
  },
  {
    name: "markPrinted",
    run: () => markPrinted(12),
    method: "POST",
    url: "/api/doctor/visits/12/printed",
    response: { ok: true },
  },
  {
    name: "regenerateVisit",
    run: () => regenerateVisit(14),
    method: "POST",
    url: "/api/doctor/visits/14/regenerate",
    response: { ok: true },
  },
  {
    name: "listUnprocessed",
    run: () => listUnprocessed(12),
    method: "GET",
    url: "/api/doctor/visits/12/unprocessed",
    response: { visit: visitHeaderStub(), entries: [] },
  },
  {
    name: "getPipelineEvents",
    run: () => getPipelineEvents(12),
    method: "GET",
    url: "/api/doctor/pipeline/12/events",
    response: {
      status: "generating",
      visit: visitHeaderStub({ status: "generating", report_available: false }),
      events: [],
    },
  },
  {
    name: "listSkills",
    run: () => listSkills(),
    method: "GET",
    url: "/api/doctor/skills",
    response: {
      skills: [{ name: "regimen-folfox", version: 1 }],
      invalid: [],
    },
  },
  {
    name: "createSkillChange",
    run: () =>
      createSkillChange("regimen-folfox", "口内炎は食事がとれたかも聞いて"),
    method: "POST",
    url: "/api/doctor/skill-changes",
    body: {
      skill_name: "regimen-folfox",
      request_text: "口内炎は食事がとれたかも聞いて",
    },
    response: { id: 3, status: "pending", diff: "--- a\n+++ b\n" },
  },
  {
    name: "listSkillChanges",
    run: () => listSkillChanges(),
    method: "GET",
    url: "/api/doctor/skill-changes",
    response: { skill_changes: [] },
  },
  {
    name: "approveSkillChange",
    run: () => approveSkillChange(3),
    method: "POST",
    url: "/api/doctor/skill-changes/3/approve",
    response: { ok: true, new_version: 2 },
  },
  {
    name: "rejectSkillChange",
    run: () => rejectSkillChange(3),
    method: "POST",
    url: "/api/doctor/skill-changes/3/reject",
    response: { ok: true },
  },
];

describe("医師 API", () => {
  it.each(cases)("$name: $method $url", async (c) => {
    const fetchMock = mockFetch(() => jsonResponse(c.response));
    await expect(c.run()).resolves.toEqual(c.response);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = callOf(fetchMock);
    expect(call.method).toBe(c.method);
    expect(call.url).toBe(c.url);
    expect(call.body).toEqual(c.body);
    expect(call.init.credentials).toBe("include");
  });

  it("reportUrl は fetch せずに URL を返す", () => {
    const fetchMock = mockFetch(() => jsonResponse({}));
    expect(reportUrl(12)).toBe("/api/doctor/visits/12/report");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("login: パスワード違いは ApiError(401)", async () => {
    mockFetch(() => jsonResponse({ error: "bad_password" }, 401));
    const err = await login("wrong").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).code).toBe("bad_password");
  });

  it("saveCourse: 矛盾は ApiError(400, code)", async () => {
    mockFetch(() => jsonResponse({ error: "infusion_order" }, 400));
    const err = await saveCourse(course).catch((e: unknown) => e);
    expect((err as ApiError).status).toBe(400);
    expect((err as ApiError).code).toBe("infusion_order");
  });
});

describe("checkDoctorSession", () => {
  it("200 ならログイン済み", async () => {
    const fetchMock = mockFetch(() =>
      jsonResponse({ skills: [], invalid: [] }),
    );
    await expect(checkDoctorSession()).resolves.toBe(true);
    expect(callOf(fetchMock).url).toBe("/api/doctor/skills");
  });

  it("401 なら未ログイン", async () => {
    mockFetch(() => jsonResponse({ error: "not_logged_in" }, 401));
    await expect(checkDoctorSession()).resolves.toBe(false);
  });

  it("401 以外の失敗はそのまま投げる", async () => {
    mockFetch(() => jsonResponse({ error: "boom" }, 500));
    await expect(checkDoctorSession()).rejects.toBeInstanceOf(ApiError);
  });
});
