import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Course } from "../../api/types";
import {
  bodiesOf,
  countOf,
  mockApi,
  renderRoute,
} from "../../components/doctor/testing";
import { jsonResponse } from "../../test/fetchMock";
import PatientDetail from "./PatientDetail";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PID = "P-DEMO0001";
const LIST = `GET /api/doctor/patients/${PID}/courses`;
const SAVE = "POST /api/doctor/courses";

const COURSES: Course[] = [
  {
    id: 2,
    patient_id: PID,
    course_no: 2,
    infusion_date: "2026-10-13",
    planned_date: "2026-10-11",
    next_visit: "2026-10-27",
    note: null,
  },
  {
    id: 1,
    patient_id: PID,
    course_no: 1,
    infusion_date: "2026-09-27",
    planned_date: null,
    next_visit: null,
    note: "初回",
  },
];

const PATIENTS = {
  patients: [
    {
      id: PID,
      regimen: "FOLFOX",
      created_at: "2026-09-20T10:00:00+09:00",
      register_url: "http://localhost:5173/register?pid=P-DEMO0001",
    },
  ],
};

function renderDetail() {
  return renderRoute(
    `/doctor/patients/${PID}`,
    "/doctor/patients/:pid",
    <PatientDetail />,
  );
}

function rowOf(label: string): HTMLElement {
  const row = screen.getByText(label).closest("tr");
  if (!row) {
    throw new Error(`${label} の行が無い`);
  }
  return row;
}

function setDate(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("PatientDetail（D2 コース登録）", () => {
  it("仮名ID・レジメンとコースを course_no 順に並べ、延期を出す", async () => {
    mockApi({
      [LIST]: { courses: COURSES },
      "GET /api/doctor/patients": PATIENTS,
    });
    renderDetail();
    expect(
      screen.getByRole("heading", { level: 1, name: "コース登録" }),
    ).toBeInTheDocument();
    expect(screen.getByText(PID)).toBeInTheDocument();
    await screen.findByText("第1コース");
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("第1コース");
    expect(rows[1]).toHaveTextContent("第2コース");
    expect(
      within(rowOf("第2コース")).getByText("予定より2日延期"),
    ).toBeInTheDocument();
    expect(within(rowOf("第1コース")).getByText("初回")).toBeInTheDocument();
    expect(await screen.findByText("FOLFOX")).toBeInTheDocument();
  });

  it("新しいコースは次の番号で始まり、保存で POST して取り直す", async () => {
    const saved: Course = {
      id: 3,
      patient_id: PID,
      course_no: 3,
      infusion_date: "2026-10-27",
      planned_date: null,
      next_visit: "2026-11-09",
      note: null,
    };
    const lists = [COURSES, [...COURSES, saved]];
    const fetchMock = mockApi({
      [LIST]: () => jsonResponse({ courses: lists.shift() ?? [] }),
      [SAVE]: saved,
    });
    renderDetail();
    await screen.findByText("第1コース");
    expect(screen.getByLabelText("コース番号")).toHaveValue(3);
    setDate("実投与日（Day1）", "2026-10-27");
    setDate("次回受診予定日", "2026-11-09");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(bodiesOf(fetchMock, SAVE)).toEqual([
      {
        patient_id: PID,
        course_no: 3,
        infusion_date: "2026-10-27",
        planned_date: null,
        next_visit: "2026-11-09",
        note: null,
      },
    ]);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "第3コースを保存しました",
    );
    expect(await screen.findByText("第3コース")).toBeInTheDocument();
    expect(countOf(fetchMock, LIST)).toBe(2);
    expect(screen.getByLabelText("コース番号")).toHaveValue(4);
  });

  it("「修正」でそのコースをフォームに入れ、id つきで送る", async () => {
    const fetchMock = mockApi({
      [LIST]: { courses: COURSES },
      [SAVE]: COURSES[0],
    });
    renderDetail();
    await screen.findByText("第2コース");
    await userEvent.click(
      within(rowOf("第2コース")).getByRole("button", { name: "修正" }),
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "第2コースを修正" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("コース番号")).toHaveValue(2);
    expect(screen.getByLabelText("コース番号")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("実投与日（Day1）")).toHaveValue("2026-10-13");
    expect(screen.getByLabelText("予定日（延期の注記に使う）")).toHaveValue(
      "2026-10-11",
    );
    setDate("実投与日（Day1）", "2026-10-14");
    await userEvent.type(screen.getByLabelText("メモ"), "（合成）延期");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(bodiesOf(fetchMock, SAVE)).toEqual([
      {
        id: 2,
        patient_id: PID,
        course_no: 2,
        infusion_date: "2026-10-14",
        planned_date: "2026-10-11",
        next_visit: "2026-10-27",
        note: "（合成）延期",
      },
    ]);
  });

  it("修正をやめると新しいコースの入力に戻る", async () => {
    mockApi({ [LIST]: { courses: COURSES } });
    renderDetail();
    await screen.findByText("第2コース");
    await userEvent.click(
      within(rowOf("第2コース")).getByRole("button", { name: "修正" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "修正をやめる" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "コースを追加" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("コース番号")).toHaveValue(3);
    expect(screen.getByLabelText("実投与日（Day1）")).toHaveValue("");
  });

  it("API の 400 の code を出す", async () => {
    mockApi({
      [LIST]: { courses: COURSES },
      [SAVE]: () => jsonResponse({ error: "course_order" }, 400),
    });
    renderDetail();
    await screen.findByText("第1コース");
    setDate("実投与日（Day1）", "2026-09-01");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("course_order");
    expect(alert).toHaveTextContent("保存できませんでした");
  });

  it.each([
    ["{ok:false}", { ok: false }],
    ["本文が空", {}],
    ["course_no が無い", { patient_id: PID, infusion_date: "2026-11-10" }],
  ])("保存の応答が 200 %s なら invalid_response を出す", async (_l, body) => {
    mockApi({ [LIST]: { courses: COURSES }, [SAVE]: body });
    renderDetail();
    await screen.findByText("第1コース");
    setDate("実投与日（Day1）", "2026-11-10");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("invalid_response");
    expect(alert).toHaveTextContent("保存できませんでした");
  });

  it("実投与日が空なら送らずに知らせる", async () => {
    const fetchMock = mockApi({ [LIST]: { courses: COURSES } });
    renderDetail();
    await screen.findByText("第1コース");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "missing_infusion_date",
    );
    expect(countOf(fetchMock, SAVE)).toBe(0);
  });

  it("コースが無ければその旨と、番号 1 から", async () => {
    mockApi({ [LIST]: { courses: [] } });
    renderDetail();
    expect(
      await screen.findByText("まだコースが登録されていません"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("コース番号")).toHaveValue(1);
  });

  it("コースが取れなければ code を出す", async () => {
    mockApi({});
    renderDetail();
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
  });

  it.each([
    ["courses が無い", { ok: true }],
    ["要素の型が違う", { courses: [{ course_no: "1" }] }],
  ])(
    "応答が契約と違えば（%s）invalid_response（0件と言わない）",
    async (_l, b) => {
      mockApi({ [LIST]: b });
      renderDetail();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.queryByText("まだコースが登録されていません")).toBeNull();
    },
  );
});
