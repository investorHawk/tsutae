/**
 * D2: 同じ画面のまま別の患者へ移ったとき、前の患者のコース・フォーム・知らせを残さず、
 * 前の患者の遅い応答を新しい患者の下に出さない（前の患者の id で送らない）。
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Course } from "../../api/types";
import {
  bodiesOf,
  deferred,
  mockApi,
  type RouteValue,
} from "../../components/doctor/testing";
import { jsonResponse } from "../../test/fetchMock";
import PatientDetail from "./PatientDetail";

afterEach(() => {
  vi.unstubAllGlobals();
});

const A = "P-AAAA0001";
const B = "P-BBBB0002";
const SAVE = "POST /api/doctor/courses";

function listKey(pid: string): string {
  return `GET /api/doctor/patients/${pid}/courses`;
}

function course(pid: string, no: number, infusion: string): Course {
  return {
    id: no + (pid === A ? 10 : 20),
    patient_id: pid,
    course_no: no,
    infusion_date: infusion,
    planned_date: null,
    next_visit: null,
    note: null,
  };
}

const A_COURSES = [
  course(A, 1, "2026-09-01"),
  course(A, 2, "2026-09-15"),
  course(A, 3, "2026-09-29"),
];
const B_COURSES = [course(B, 1, "2026-10-27")];

function GoTo({ pid }: { pid: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(`/doctor/patients/${pid}`)}>
      go {pid}
    </button>
  );
}

function renderAt(routes: Record<string, RouteValue>) {
  const fetchMock = mockApi({
    "GET /api/doctor/patients": { patients: [] },
    ...routes,
  });
  render(
    <MemoryRouter initialEntries={[`/doctor/patients/${A}`]}>
      <Routes>
        <Route path="/doctor/patients/:pid" element={<PatientDetail />} />
      </Routes>
      <GoTo pid={B} />
    </MemoryRouter>,
  );
  return fetchMock;
}

function goToB() {
  fireEvent.click(screen.getByRole("button", { name: `go ${B}` }));
}

describe("PatientDetail の患者の切り替え", () => {
  it("前の患者の遅い一覧は、移った後の患者の下に出さない", async () => {
    const slowA = deferred<Response>();
    renderAt({
      [listKey(A)]: () => slowA.promise,
      [listKey(B)]: { courses: B_COURSES },
    });
    goToB();
    expect(await screen.findByText("第1コース")).toBeInTheDocument();
    expect(screen.getByText(B)).toBeInTheDocument();
    await act(async () => {
      slowA.resolve(jsonResponse({ courses: A_COURSES }));
    });
    expect(screen.queryByText("第3コース")).toBeNull();
    expect(screen.queryByText("2026-09-01")).toBeNull();
    expect(screen.getByLabelText("コース番号")).toHaveValue(2);
  });

  it("前の患者のコースと修正中のフォームを、移った直後に消す", async () => {
    const slowB = deferred<Response>();
    const fetchMock = renderAt({
      [listKey(A)]: { courses: A_COURSES },
      [listKey(B)]: () => slowB.promise,
      [SAVE]: course(B, 1, "2026-11-10"),
    });
    const row = (await screen.findByText("第2コース")).closest("tr");
    await userEvent.click(within(row!).getByRole("button", { name: "修正" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "第2コースを修正" }),
    ).toBeInTheDocument();
    goToB();
    expect(screen.getByText(B)).toBeInTheDocument();
    expect(screen.queryByText("第2コース")).toBeNull();
    expect(
      screen.getByRole("heading", { level: 2, name: "コースを追加" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("コース番号")).toHaveValue(1);
    expect(screen.getByLabelText("実投与日（Day1）")).toHaveValue("");
    // 新しい患者の一覧がまだでも、送るのは新しい患者の新しいコース（A の id は付かない）
    fireEvent.change(screen.getByLabelText("実投与日（Day1）"), {
      target: { value: "2026-11-10" },
    });
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(bodiesOf(fetchMock, SAVE)).toEqual([
      {
        patient_id: B,
        course_no: 1,
        infusion_date: "2026-11-10",
        planned_date: null,
        next_visit: null,
        note: null,
      },
    ]);
    await act(async () => {
      slowB.resolve(jsonResponse({ courses: [course(B, 1, "2026-11-10")] }));
    });
  });

  it("移った後の保存は、前の患者のコースの id を付けず、新しい患者で送る", async () => {
    const saved = course(B, 2, "2026-11-10");
    const fetchMock = renderAt({
      [listKey(A)]: { courses: A_COURSES },
      [listKey(B)]: { courses: B_COURSES },
      [SAVE]: saved,
    });
    const row = (await screen.findByText("第3コース")).closest("tr");
    await userEvent.click(within(row!).getByRole("button", { name: "修正" }));
    goToB();
    await screen.findByText("第1コース");
    expect(screen.queryByText("第3コース")).toBeNull();
    fireEvent.change(screen.getByLabelText("実投与日（Day1）"), {
      target: { value: "2026-11-10" },
    });
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(bodiesOf(fetchMock, SAVE)).toEqual([
      {
        patient_id: B,
        course_no: 2,
        infusion_date: "2026-11-10",
        planned_date: null,
        next_visit: null,
        note: null,
      },
    ]);
  });
});
