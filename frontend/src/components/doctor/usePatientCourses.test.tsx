import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Course } from "../../api/types";
import { jsonResponse } from "../../test/fetchMock";
import { deferred, mockApi } from "./testing";
import { usePatientCourses } from "./usePatientCourses";

afterEach(() => {
  vi.unstubAllGlobals();
});

const A = "P-AAAA0001";
const B = "P-BBBB0002";

function course(pid: string, no: number): Course {
  return {
    id: no,
    patient_id: pid,
    course_no: no,
    infusion_date: "2026-10-13",
    planned_date: null,
    next_visit: null,
    note: null,
  };
}

const patients = {
  patients: [
    {
      id: A,
      regimen: "FOLFOX",
      created_at: "2026-09-20T10:00:00+09:00",
      register_url: `http://localhost:5173/register?pid=${A}`,
    },
    {
      id: B,
      regimen: "CAPOX",
      created_at: "2026-09-21T10:00:00+09:00",
      register_url: `http://localhost:5173/register?pid=${B}`,
    },
  ],
};

const handleError = (err: unknown) =>
  err instanceof Error ? err.message : "error";

function renderCourses(pid: string) {
  return renderHook(
    ({ pid: current }) => usePatientCourses(current, handleError),
    { initialProps: { pid } },
  );
}

describe("usePatientCourses の患者の切り替え", () => {
  it("切り替えたら前の患者のコース・失敗・レジメンをすぐに消す", async () => {
    const slowB = deferred<Response>();
    mockApi({
      [`GET /api/doctor/patients/${A}/courses`]: { courses: [course(A, 1)] },
      [`GET /api/doctor/patients/${B}/courses`]: () => slowB.promise,
      "GET /api/doctor/patients": patients,
    });
    const { result, rerender } = renderCourses(A);
    await act(async () => {
      await result.current.reload();
    });
    await waitFor(() => expect(result.current.regimen).toBe("FOLFOX"));
    expect(result.current.courses).toEqual([course(A, 1)]);

    rerender({ pid: B });
    expect(result.current.courses).toBeNull();
    expect(result.current.loadError).toBeNull();
    expect(result.current.regimen).toBeNull();
    await waitFor(() => expect(result.current.regimen).toBe("CAPOX"));
    await act(async () => {
      slowB.resolve(jsonResponse({ courses: [course(B, 1)] }));
    });
  });

  it("前の患者の遅い応答は、後から返っても使わない（null を返す）", async () => {
    const slowA = deferred<Response>();
    mockApi({
      [`GET /api/doctor/patients/${A}/courses`]: () => slowA.promise,
      [`GET /api/doctor/patients/${B}/courses`]: {
        courses: [course(B, 2), course(B, 1)],
      },
      "GET /api/doctor/patients": patients,
    });
    const { result, rerender } = renderCourses(A);
    let fromA: Promise<Course[] | null> = Promise.resolve(null);
    act(() => {
      fromA = result.current.reload();
    });
    rerender({ pid: B });
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.courses?.map((c) => c.patient_id)).toEqual([B, B]);

    await act(async () => {
      slowA.resolve(jsonResponse({ courses: [course(A, 1)] }));
      expect(await fromA).toBeNull();
    });
    expect(result.current.courses).toEqual([course(B, 1), course(B, 2)]);
  });

  it("前の患者の遅い失敗も、切り替えた後の画面に出さない", async () => {
    const slowA = deferred<Response>();
    mockApi({
      [`GET /api/doctor/patients/${A}/courses`]: () => slowA.promise,
      [`GET /api/doctor/patients/${B}/courses`]: { courses: [] },
      "GET /api/doctor/patients": patients,
    });
    const { result, rerender } = renderCourses(A);
    let fromA: Promise<Course[] | null> = Promise.resolve(null);
    act(() => {
      fromA = result.current.reload();
    });
    rerender({ pid: B });
    await act(async () => {
      await result.current.reload();
    });
    await act(async () => {
      slowA.resolve(jsonResponse({ error: "server_error" }, 500));
      await fromA;
    });
    expect(result.current.loadError).toBeNull();
    expect(result.current.courses).toEqual([]);
  });

  it("同じ患者で取り直しが重なったら、最後の取り直しだけを使う", async () => {
    const first = deferred<Response>();
    const answers: Array<() => Promise<Response> | Response> = [
      () => first.promise,
      () => jsonResponse({ courses: [course(A, 1), course(A, 2)] }),
    ];
    mockApi({
      [`GET /api/doctor/patients/${A}/courses`]: () => answers.shift()!(),
      "GET /api/doctor/patients": patients,
    });
    const { result } = renderCourses(A);
    let older: Promise<Course[] | null> = Promise.resolve(null);
    act(() => {
      older = result.current.reload();
    });
    await act(async () => {
      await result.current.reload();
    });
    await act(async () => {
      first.resolve(jsonResponse({ courses: [course(A, 1)] }));
      expect(await older).toBeNull();
    });
    expect(result.current.courses).toHaveLength(2);
  });
});
