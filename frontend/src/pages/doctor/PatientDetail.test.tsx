import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Course } from "../../api/types";
import {
  bodiesOf,
  countOf,
  mockApi,
  renderRoute,
  type RouteValue,
} from "../../components/doctor/testing";
import { doctorPatientStub } from "../../test/doctorStubs";
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
    doctorPatientStub({
      id: PID,
      last_record_date: null,
      days_since_last_record: null,
      record_stale: true,
      current_course_no: null,
      current_day: null,
      next_visit: null,
    }),
  ],
};

/** 「＋ コースを追加」で入力の欄を開く。 */
async function openAdd() {
  await userEvent.click(
    screen.getByRole("button", { name: "＋ コースを追加" }),
  );
}

/** 記録・受診の節（D4-1）の経路を既定で空にして mockApi に渡す。 */
function mockDetail(routes: Record<string, RouteValue>) {
  return mockApi({
    [`GET /api/doctor/patients/${PID}/visits`]: { visits: [] },
    [`GET /api/doctor/patients/${PID}/entries`]: { entries: [], total: 0 },
    ...routes,
  });
}

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
    mockDetail({
      [LIST]: { courses: COURSES },
      "GET /api/doctor/patients": PATIENTS,
    });
    renderDetail();
    expect(
      screen.getByRole("heading", { level: 1, name: `患者 ${PID}` }),
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
    const fetchMock = mockDetail({
      [LIST]: () => jsonResponse({ courses: lists.shift() ?? [] }),
      [SAVE]: saved,
    });
    renderDetail();
    await screen.findByText("第1コース");
    await openAdd();
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
    // 保存できたら欄を閉じる。次に開くと次の番号から
    expect(screen.queryByLabelText("コース番号")).toBeNull();
    await openAdd();
    expect(screen.getByLabelText("コース番号")).toHaveValue(4);
  });

  it("「修正」でそのコースをフォームに入れ、id つきで送る", async () => {
    const fetchMock = mockDetail({
      [LIST]: { courses: COURSES },
      [SAVE]: COURSES[0],
    });
    renderDetail();
    await screen.findByText("第2コース");
    await userEvent.click(
      within(rowOf("第2コース")).getByRole("button", { name: "修正" }),
    );
    expect(
      screen.getByRole("heading", { level: 3, name: "第2コースを修正" }),
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

  it("修正をやめると欄を閉じ、次に開くと新しいコースの入力になる", async () => {
    mockDetail({ [LIST]: { courses: COURSES } });
    renderDetail();
    await screen.findByText("第2コース");
    await userEvent.click(
      within(rowOf("第2コース")).getByRole("button", { name: "修正" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "修正をやめる" }));
    expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
    await openAdd();
    expect(
      screen.getByRole("heading", { level: 3, name: "コースを追加" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("コース番号")).toHaveValue(3);
    expect(screen.getByLabelText("実投与日（Day1）")).toHaveValue("");
  });

  it("入力の欄は普段は閉じていて、「やめる」で閉じると入力を捨てる", async () => {
    mockDetail({ [LIST]: { courses: COURSES } });
    renderDetail();
    await screen.findByText("第1コース");
    expect(screen.queryByLabelText("コース番号")).toBeNull();
    await openAdd();
    expect(
      screen.queryByRole("button", { name: "＋ コースを追加" }),
    ).toBeNull();
    setDate("実投与日（Day1）", "2026-10-27");
    await userEvent.click(screen.getByRole("button", { name: "やめる" }));
    expect(screen.queryByLabelText("コース番号")).toBeNull();
    await openAdd();
    expect(screen.getByLabelText("実投与日（Day1）")).toHaveValue("");
  });

  it("保存に失敗したら入力を残して開いたまま", async () => {
    mockDetail({
      [LIST]: { courses: COURSES },
      [SAVE]: () => jsonResponse({ error: "course_order" }, 400),
    });
    renderDetail();
    await screen.findByText("第1コース");
    await openAdd();
    setDate("実投与日（Day1）", "2026-09-01");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("実投与日（Day1）")).toHaveValue("2026-09-01");
  });

  it("延期の説明は入力欄の上にある（保存ボタンの下ではない。D4-2）", async () => {
    mockDetail({ [LIST]: { courses: COURSES } });
    renderDetail();
    await screen.findByText("第1コース");
    await openAdd();
    const help = screen.getByText(/延期があれば、実投与日を実際の日に直し/);
    const input = screen.getByLabelText("実投与日（Day1）");
    const save = screen.getByRole("button", { name: "保存" });
    const before = Node.DOCUMENT_POSITION_FOLLOWING;
    expect(help.compareDocumentPosition(input) & before).toBeTruthy();
    expect(help.compareDocumentPosition(save) & before).toBeTruthy();
  });

  it("API の 400 の code を出す", async () => {
    mockDetail({
      [LIST]: { courses: COURSES },
      [SAVE]: () => jsonResponse({ error: "course_order" }, 400),
    });
    renderDetail();
    await screen.findByText("第1コース");
    await openAdd();
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
    mockDetail({ [LIST]: { courses: COURSES }, [SAVE]: body });
    renderDetail();
    await screen.findByText("第1コース");
    await openAdd();
    setDate("実投与日（Day1）", "2026-11-10");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("invalid_response");
    expect(alert).toHaveTextContent("保存できませんでした");
  });

  it("実投与日が空なら送らずに知らせる", async () => {
    const fetchMock = mockDetail({ [LIST]: { courses: COURSES } });
    renderDetail();
    await screen.findByText("第1コース");
    await openAdd();
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "missing_infusion_date",
    );
    expect(countOf(fetchMock, SAVE)).toBe(0);
  });

  it("コースが無ければその旨と、番号 1 から", async () => {
    mockDetail({ [LIST]: { courses: [] } });
    renderDetail();
    expect(
      await screen.findByText("まだコースが登録されていません"),
    ).toBeInTheDocument();
    await openAdd();
    expect(screen.getByLabelText("コース番号")).toHaveValue(1);
  });

  it("コースが取れなければ code を出す", async () => {
    mockDetail({});
    renderDetail();
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
  });

  it.each([
    ["courses が無い", { ok: true }],
    ["要素の型が違う", { courses: [{ course_no: "1" }] }],
  ])(
    "応答が契約と違えば（%s）invalid_response（0件と言わない）",
    async (_l, b) => {
      mockDetail({ [LIST]: b });
      renderDetail();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.queryByText("まだコースが登録されていません")).toBeNull();
    },
  );
});
