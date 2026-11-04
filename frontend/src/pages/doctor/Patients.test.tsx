import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QRCode from "qrcode";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DoctorPatient } from "../../api/types";
import { QR_OPTIONS, svgDataUrl } from "../../components/doctor/QrImage";
import {
  bodiesOf,
  countOf,
  mockApi,
  renderRoute,
} from "../../components/doctor/testing";
import { fixtureBody } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import Patients from "./Patients";

afterEach(() => {
  vi.unstubAllGlobals();
});

const LIST = "GET /api/doctor/patients";
const CREATE = "POST /api/doctor/patients";
const BASE = "http://localhost:5173/register?pid=";

const PATIENTS: DoctorPatient[] = [
  {
    id: "P-DEMO0001",
    regimen: "FOLFOX",
    created_at: "2026-09-20T10:00:00+09:00",
    register_url: `${BASE}P-DEMO0001`,
    last_record_date: "2026-11-05",
    current_course_no: 3,
    next_visit: "2026-11-10",
  },
  {
    id: "P-EVALA001",
    regimen: "CAPOX",
    created_at: "2026-09-21T10:00:00+09:00",
    register_url: `${BASE}P-EVALA001`,
    last_record_date: null,
    current_course_no: null,
    next_visit: null,
  },
];

function renderPatients() {
  return renderRoute("/doctor/patients", "/doctor/patients", <Patients />);
}

function rowOf(pid: string): HTMLElement {
  const row = screen.getByRole("link", { name: pid }).closest("tr");
  if (!row) {
    throw new Error(`${pid} の行が無い`);
  }
  return row;
}

describe("Patients（D1 患者一覧）", () => {
  it("仮名ID・レジメンを並べ、仮名IDから D2 へ", async () => {
    mockApi({ [LIST]: { patients: PATIENTS } });
    renderPatients();
    expect(
      screen.getByRole("heading", { level: 1, name: "患者一覧" }),
    ).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "P-DEMO0001" });
    expect(link).toHaveAttribute("href", "/doctor/patients/P-DEMO0001");
    expect(within(rowOf("P-EVALA001")).getByText("CAPOX")).toBeInTheDocument();
  });

  it("最後の記録日・今のコース・次回受診の列（無ければ —）", async () => {
    mockApi({ [LIST]: { patients: PATIENTS } });
    renderPatients();
    await screen.findByRole("link", { name: "P-DEMO0001" });
    const headers = screen
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual(
      expect.arrayContaining(["最後の記録日", "今のコース", "次回受診"]),
    );
    const demo = within(rowOf("P-DEMO0001"));
    expect(demo.getByText("2026-11-05")).toBeInTheDocument();
    expect(demo.getByText("第3コース")).toBeInTheDocument();
    expect(demo.getByText("2026-11-10")).toBeInTheDocument();
    expect(within(rowOf("P-EVALA001")).getAllByText("—")).toHaveLength(3);
  });

  it("実際の API の応答（fixture）をそのまま並べる", async () => {
    mockApi({ [LIST]: fixtureBody("doctor_patients") as object });
    renderPatients();
    const demo = within(
      (await screen.findByRole("link", { name: "P-DEMO0001" })).closest(
        "tr",
      ) as HTMLElement,
    );
    expect(demo.getByText("第3コース")).toBeInTheDocument();
  });

  it("「患者を追加」は小見出し付きの枠で、一覧と分かれている", async () => {
    mockApi({ [LIST]: { patients: PATIENTS } });
    renderPatients();
    await screen.findByRole("link", { name: "P-DEMO0001" });
    const box = screen.getByRole("region", { name: "患者を追加" });
    expect(
      within(box).getByRole("heading", { level: 2, name: "患者を追加" }),
    ).toBeInTheDocument();
    expect(within(box).getByLabelText("レジメン")).toBeInTheDocument();
    expect(
      within(box).getByRole("button", { name: "患者を追加" }),
    ).toBeInTheDocument();
    expect(within(box).queryByRole("table")).toBeNull();
  });

  it("氏名の欄は無い", async () => {
    mockApi({ [LIST]: { patients: PATIENTS } });
    renderPatients();
    await screen.findByRole("link", { name: "P-DEMO0001" });
    expect(screen.queryByText(/氏名/)).toBeNull();
    expect(screen.queryByLabelText(/名前/)).toBeNull();
  });

  it("行の「登録用QR」でその患者の register_url の QR を描く", async () => {
    mockApi({ [LIST]: { patients: PATIENTS } });
    renderPatients();
    await screen.findByRole("link", { name: "P-DEMO0001" });
    await userEvent.click(
      within(rowOf("P-EVALA001")).getByRole("button", { name: "登録用QR" }),
    );
    const img = await screen.findByRole("img", {
      name: "P-EVALA001 の登録用QR",
    });
    const expected = svgDataUrl(
      await QRCode.toString(`${BASE}P-EVALA001`, QR_OPTIONS),
    );
    expect(img).toHaveAttribute("src", expected);
    expect(screen.getByText(`${BASE}P-EVALA001`)).toBeInTheDocument();
  });

  it("QR はもう一度押すと閉じる", async () => {
    mockApi({ [LIST]: { patients: PATIENTS } });
    renderPatients();
    await screen.findByRole("link", { name: "P-DEMO0001" });
    const button = within(rowOf("P-DEMO0001")).getByRole("button", {
      name: "登録用QR",
    });
    await userEvent.click(button);
    await screen.findByRole("img", { name: "P-DEMO0001 の登録用QR" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(button);
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("レジメンを選んで患者を追加 → 一覧を取り直し、新しい患者の QR を出す", async () => {
    const created: DoctorPatient = {
      id: "P-NEW00001",
      regimen: "CAPOX",
      created_at: "2026-11-09T10:00:00+09:00",
      register_url: `${BASE}P-NEW00001`,
      last_record_date: null,
      current_course_no: null,
      next_visit: null,
    };
    const lists = [PATIENTS, [...PATIENTS, created]];
    const fetchMock = mockApi({
      [LIST]: () => jsonResponse({ patients: lists.shift() ?? [] }),
      [CREATE]: { id: created.id, register_url: created.register_url },
    });
    renderPatients();
    await screen.findByRole("link", { name: "P-DEMO0001" });
    await userEvent.selectOptions(screen.getByLabelText("レジメン"), "CAPOX");
    await userEvent.click(screen.getByRole("button", { name: "患者を追加" }));
    expect(bodiesOf(fetchMock, CREATE)).toEqual([{ regimen: "CAPOX" }]);
    expect(
      await screen.findByRole("img", { name: "P-NEW00001 の登録用QR" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: "P-NEW00001" }),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, LIST)).toBe(2);
    expect(screen.getByRole("status")).toHaveTextContent("P-NEW00001");
  });

  it("作成に失敗したら code を出す", async () => {
    mockApi({
      [LIST]: { patients: PATIENTS },
      [CREATE]: () => jsonResponse({ error: "invalid_regimen" }, 400),
    });
    renderPatients();
    await screen.findByRole("link", { name: "P-DEMO0001" });
    await userEvent.click(screen.getByRole("button", { name: "患者を追加" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid_regimen",
    );
  });

  it.each([
    ["本文が空", {}],
    ["register_url が無い", { id: "P-NEW00001" }],
  ])(
    "作成の応答が契約と違えば（%s）invalid_response、QR は出さない",
    async (_l, body) => {
      mockApi({ [LIST]: { patients: PATIENTS }, [CREATE]: body });
      renderPatients();
      await screen.findByRole("link", { name: "P-DEMO0001" });
      await userEvent.click(screen.getByRole("button", { name: "患者を追加" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.queryByRole("img")).toBeNull();
    },
  );

  it("患者がいなければその旨", async () => {
    mockApi({ [LIST]: { patients: [] } });
    renderPatients();
    expect(
      await screen.findByText("登録された患者はいません"),
    ).toBeInTheDocument();
  });

  it("一覧が取れなければ code を出す（見出しは出す）", async () => {
    mockApi({});
    renderPatients();
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
    expect(
      screen.getByRole("heading", { level: 1, name: "患者一覧" }),
    ).toBeInTheDocument();
  });

  it.each([
    ["patients が無い", { ok: true }],
    ["要素の型が違う", { patients: [{ id: 1, regimen: "FOLFOX" }] }],
  ])(
    "応答が契約と違えば（%s）invalid_response（0件と言わない）",
    async (_l, b) => {
      mockApi({ [LIST]: b });
      renderPatients();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.queryByText("登録された患者はいません")).toBeNull();
    },
  );
});
