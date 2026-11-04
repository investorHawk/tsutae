/**
 * D2 患者の画面の「記録」「受診」の節（D4-1）。コースの節は PatientDetail.test.tsx。
 * 記録は直近の一覧（日付・クローズ回答の短い表記・自由記載の有無。原文は出さない）、
 * 受診は印刷済み・期限切れも含めて新しい順（レポートを開けるのは印刷待ちだけ）。
 */
import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DoctorEntry, PatientVisit } from "../../api/types";
import {
  mockApi,
  renderRoute,
  type RouteValue,
} from "../../components/doctor/testing";
import { fixtureBody } from "../../test/apiFixtures";
import PatientDetail from "./PatientDetail";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PID = "P-DEMO0001";
const COURSES = `GET /api/doctor/patients/${PID}/courses`;
const VISITS = `GET /api/doctor/patients/${PID}/visits`;
const ENTRIES = `GET /api/doctor/patients/${PID}/entries`;

function entry(patch: Partial<DoctorEntry>): DoctorEntry {
  return {
    id: 1,
    recorded_at: "2026-11-05T20:00:00+09:00",
    record_date: "2026-11-05",
    kind: "answers",
    by_proxy: false,
    answers: [],
    has_free_text: false,
    ...patch,
  };
}

function visit(patch: Partial<PatientVisit>): PatientVisit {
  return {
    id: 12,
    reception_no: "A-023",
    visit_date: "2026-11-09",
    created_at: "2026-11-09T09:40:00+09:00",
    status: "ready",
    fallback: false,
    report_available: true,
    unprocessed_count: 0,
    ...patch,
  };
}

function renderWith(routes: Record<string, RouteValue>) {
  mockApi({
    [COURSES]: { courses: [] },
    "GET /api/doctor/patients": { patients: [] },
    [VISITS]: { visits: [] },
    [ENTRIES]: { entries: [], total: 0 },
    ...routes,
  });
  return renderRoute(
    `/doctor/patients/${PID}`,
    "/doctor/patients/:pid",
    <PatientDetail />,
  );
}

function section(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

describe("PatientDetail の見出しと節", () => {
  it("見出しは「患者 <仮名ID>」で、コース・記録・受診の節がこの順にある", async () => {
    renderWith({});
    expect(
      screen.getByRole("heading", { level: 1, name: `患者 ${PID}` }),
    ).toBeInTheDocument();
    const names = screen
      .getAllByRole("heading", { level: 2 })
      .map((h) => h.textContent);
    expect(names).toEqual(["コース", "記録", "受診"]);
    await screen.findByText("まだ記録はありません");
  });
});

describe("PatientDetail の記録の節", () => {
  it("日付・クローズ回答の短い表記・自由記載の有無を新しい順に出す（原文は出さない）", async () => {
    renderWith({
      [ENTRIES]: {
        entries: [
          entry({
            id: 2,
            record_date: "2026-11-06",
            kind: "mixed",
            by_proxy: true,
            answers: [
              { question_key: "fever", value: "measured", temperature: 38.2 },
              { question_key: "diarrhea", value: "hard", temperature: null },
              { question_key: "numbness", value: "none", temperature: null },
            ],
            has_free_text: true,
          }),
          entry({ id: 1, kind: "too_sick" }),
        ],
        total: 2,
      },
    });
    const box = section("記録");
    const rows = (await within(box).findAllByRole("row")).slice(1);
    expect(rows).toHaveLength(2);
    const first = within(rows[0]);
    expect(first.getByText("2026-11-06")).toBeInTheDocument();
    expect(first.getByText("体温 38.2℃")).toBeInTheDocument();
    expect(first.getByText("下痢 つらい")).toBeInTheDocument();
    expect(first.getByText("しびれ なし")).toBeInTheDocument();
    expect(first.getByText("あり")).toBeInTheDocument();
    expect(first.getByText("代")).toBeInTheDocument();
    const second = within(rows[1]);
    expect(second.getByText("つらくて書けない")).toBeInTheDocument();
    expect(second.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("直近だけを出しているときは総数も出す", async () => {
    renderWith({
      [ENTRIES]: { entries: [entry({})], total: 45 },
    });
    expect(
      await within(section("記録")).findByText(/全 45 件のうち新しい 1 件/),
    ).toBeInTheDocument();
  });

  it("実際の API の応答（fixture）をそのまま並べる", async () => {
    renderWith({ [ENTRIES]: fixtureBody("doctor_patient_entries") as object });
    const rows = (await within(section("記録")).findAllByRole("row")).slice(1);
    expect(within(rows[0]).getByText("体温 38.2℃")).toBeInTheDocument();
    expect(within(rows[0]).getByText("下痢 ある")).toBeInTheDocument();
  });

  it("記録が取れなければ code を出す（他の節は使える）", async () => {
    renderWith({ [ENTRIES]: { entries: "x" } });
    expect(await within(section("記録")).findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
    expect(screen.getByLabelText("コース番号")).toBeInTheDocument();
  });
});

describe("PatientDetail の受診の節", () => {
  it("受付番号・日付・状態と、印刷待ちには「レポートを開く」", async () => {
    renderWith({
      [VISITS]: {
        visits: [
          visit({ id: 13, unprocessed_count: 1 }),
          visit({
            id: 11,
            reception_no: null,
            visit_date: "2026-10-27",
            status: "printed",
            report_available: false,
          }),
          visit({
            id: 9,
            reception_no: null,
            visit_date: "2026-10-13",
            status: "ready",
            report_available: false,
          }),
        ],
      },
    });
    const box = section("受診");
    const rows = (await within(box).findAllByRole("row")).slice(1);
    expect(rows).toHaveLength(3);
    const open = within(rows[0]);
    expect(open.getByText("A-023")).toBeInTheDocument();
    expect(open.getByText("2026-11-09")).toBeInTheDocument();
    expect(open.getByText("印刷待ち")).toHaveClass("d-status--ready");
    const report = open.getByRole("link", { name: "レポートを開く" });
    expect(report).toHaveAttribute("href", "/api/doctor/visits/13/report");
    expect(report).toHaveAttribute("target", "_blank");
    expect(
      open.getByRole("link", { name: "未処理 1 件を見る →" }),
    ).toHaveAttribute("href", "/doctor/unprocessed/13");
    const printed = within(rows[1]);
    expect(printed.getByText("印刷済み")).toBeInTheDocument();
    expect(printed.queryByRole("link")).toBeNull();
    const expired = within(rows[2]);
    expect(expired.getByText("期限切れ")).toBeInTheDocument();
    expect(expired.queryByRole("link")).toBeNull();
  });

  it("レポートが消えることを注記する", async () => {
    renderWith({ [VISITS]: { visits: [visit({})] } });
    expect(
      await within(section("受診")).findByText(/印刷済みにするか 24 時間/),
    ).toBeInTheDocument();
  });

  it("受診が無ければその旨", async () => {
    renderWith({});
    expect(
      await within(section("受診")).findByText("まだ受診はありません"),
    ).toBeInTheDocument();
  });

  it("実際の API の応答（fixture）をそのまま並べる", async () => {
    renderWith({ [VISITS]: fixtureBody("doctor_patient_visits") as object });
    const rows = (await within(section("受診")).findAllByRole("row")).slice(1);
    expect(within(rows[0]).getByText("印刷済み")).toBeInTheDocument();
    expect(within(rows[0]).getByText("—")).toBeInTheDocument();
  });

  it("受診が取れなければ code を出す", async () => {
    renderWith({ [VISITS]: { visits: [{ id: "x" }] } });
    expect(await within(section("受診")).findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
  });
});
