/**
 * D2 患者の画面の要約の行・「印刷待ちの受診」・「記録」（経過表と受診日の線）・「受診」の節。
 * コースの節は PatientDetail.test.tsx。
 * 記録は日付の行 × 症状の列（原文は出さない）、受診は印刷済み・期限切れも含めて新しい順
 * （レポートを開けるのは印刷待ちだけ）。
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  countOf,
  mockApi,
  renderRoute,
  type RouteValue,
} from "../../components/doctor/testing";
import { fixtureBody } from "../../test/apiFixtures";
import {
  doctorEntryStub as entry,
  doctorPatientStub,
  patientVisitStub as visit,
} from "../../test/doctorStubs";
import PatientDetail from "./PatientDetail";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PID = "P-DEMO0001";
const COURSES = `GET /api/doctor/patients/${PID}/courses`;
const VISITS = `GET /api/doctor/patients/${PID}/visits`;
const ENTRIES = `GET /api/doctor/patients/${PID}/entries`;
const PATIENTS = "GET /api/doctor/patients";

function renderWith(routes: Record<string, RouteValue>) {
  const fetchMock = mockApi({
    [COURSES]: { courses: [] },
    [PATIENTS]: { patients: [] },
    [VISITS]: { visits: [] },
    [ENTRIES]: { entries: [], total: 0 },
    ...routes,
  });
  renderRoute(
    `/doctor/patients/${PID}`,
    "/doctor/patients/:pid",
    <PatientDetail />,
  );
  return fetchMock;
}

function section(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

function bodyRows(box: HTMLElement): HTMLElement[] {
  return within(box).getAllByRole("row").slice(1);
}

const level = (question_key: string, value: "none" | "present" | "hard") => ({
  question_key,
  value,
  temperature: null,
});

describe("PatientDetail の見出しと節", () => {
  it("見出しは「患者 <仮名ID>」で、節は コース・記録・受診 の順（印刷待ちが無ければ出さない）", async () => {
    renderWith({});
    expect(
      screen.getByRole("heading", { level: 1, name: `患者 ${PID}` }),
    ).toBeInTheDocument();
    await screen.findByText("まだ記録はありません");
    const names = screen
      .getAllByRole("heading", { level: 2 })
      .map((h) => h.textContent);
    expect(names).toEqual(["コース", "記録", "受診"]);
  });

  it("印刷待ち・生成中の受診はコースより上に出す", async () => {
    renderWith({
      [VISITS]: {
        visits: [
          visit({ id: 13, unprocessed_count: 1 }),
          visit({
            id: 12,
            reception_no: "A-020",
            status: "generating",
            report_available: false,
          }),
          visit({
            id: 11,
            reception_no: null,
            visit_date: "2026-10-27",
            created_at: "2026-10-27T10:00:00+09:00",
            status: "printed",
            report_available: false,
          }),
        ],
      },
    });
    const box = await screen.findByRole("region", { name: "印刷待ちの受診" });
    const names = screen
      .getAllByRole("heading", { level: 2 })
      .map((h) => h.textContent);
    expect(names).toEqual(["印刷待ちの受診", "コース", "記録", "受診"]);
    const rows = bodyRows(box);
    expect(rows).toHaveLength(2); // 印刷済みは出さない
    const ready = within(rows[0]!);
    expect(ready.getByText("A-023")).toBeInTheDocument();
    expect(ready.getByText("印刷待ち")).toHaveClass("d-status--ready");
    expect(ready.getByText("11月9日（月）09:40")).toBeInTheDocument();
    expect(ready.getByRole("link", { name: "レポートを開く" })).toHaveAttribute(
      "href",
      "/api/doctor/visits/13/report",
    );
    expect(ready.getByRole("link", { name: "要確認 1件" })).toHaveAttribute(
      "href",
      "/doctor/unprocessed/13",
    );
    const generating = within(rows[1]!);
    expect(generating.getByText("生成中")).toBeInTheDocument();
    expect(generating.queryByRole("link")).toBeNull();
  });
});

describe("PatientDetail の要約の行", () => {
  it("レジメン・今のコースと Day・最後の記録日・次回受診（API の値）", async () => {
    renderWith({ [PATIENTS]: { patients: [doctorPatientStub()] } });
    const box = screen.getByLabelText("患者の要約");
    expect(await within(box).findByText("第3コース Day14")).toBeInTheDocument();
    expect(within(box).getByText("FOLFOX")).toBeInTheDocument();
    expect(within(box).getByText("11月9日（月）")).toBeInTheDocument();
    expect(within(box).getByText("11月23日（月）")).toBeInTheDocument();
    expect(within(box).queryByText(/記録なし/)).toBeNull();
  });

  it("記録が途切れていれば橙の印", async () => {
    renderWith({
      [PATIENTS]: {
        patients: [
          doctorPatientStub({
            last_record_date: "2026-10-28",
            days_since_last_record: 12,
            record_stale: true,
          }),
        ],
      },
    });
    const box = screen.getByLabelText("患者の要約");
    expect(await within(box).findByText("3日以上記録なし")).toHaveClass(
      "d-flag",
    );
    expect(within(box).getByText("12日前")).toBeInTheDocument();
  });

  it("患者の行が無ければ「—」", async () => {
    renderWith({});
    await screen.findByText("まだ記録はありません");
    const box = screen.getByLabelText("患者の要約");
    expect(within(box).getAllByText("—")).toHaveLength(4);
  });

  it("コースを保存したら要約の行も取り直す（今のコース・Day が変わる）", async () => {
    const saved = {
      id: 1,
      patient_id: PID,
      course_no: 1,
      infusion_date: "2026-10-27",
      planned_date: null,
      next_visit: null,
      note: null,
    };
    const fetchMock = renderWith({
      [PATIENTS]: { patients: [doctorPatientStub()] },
      "POST /api/doctor/courses": saved,
    });
    await screen.findByText("第3コース Day14");
    await userEvent.click(
      screen.getByRole("button", { name: "＋ コースを追加" }),
    );
    fireEvent.change(screen.getByLabelText("実投与日（Day1）"), {
      target: { value: "2026-10-27" },
    });
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(countOf(fetchMock, PATIENTS)).toBe(2));
  });
});

describe("PatientDetail の記録の経過表", () => {
  it("記録日（日付と時刻）・Day・症状ごとの列・体温・自由記載・代理", async () => {
    renderWith({
      [ENTRIES]: {
        entries: [
          entry({
            id: 2,
            recorded_at: "2026-11-06T20:05:00+09:00",
            record_date: "2026-11-06",
            day: 11,
            kind: "mixed",
            by_proxy: true,
            answers: [
              { question_key: "fever", value: "measured", temperature: 38.2 },
              level("diarrhea", "hard"),
              level("numbness", "none"),
              level("stomatitis", "present"),
            ],
            has_free_text: true,
          }),
          entry({ id: 1, kind: "too_sick" }),
        ],
        total: 2,
      },
    });
    const box = section("記録");
    await within(box).findByText("つらくて書けない");
    const headers = within(box)
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual([
      "記録日",
      "Day",
      "しびれ",
      "下痢",
      "口内炎",
      "体温",
      "自由記載",
      "代理",
    ]);
    const [first, second] = bodyRows(box);
    const cells = within(first!).getAllByRole("cell");
    expect(within(first!).getByRole("rowheader")).toHaveTextContent(
      "11月6日（金）20:05",
    );
    expect(cells.map((c) => c.textContent)).toEqual([
      "Day11",
      "—なし",
      "つらい",
      "ある",
      "38.2℃",
      "あり",
      "代",
    ]);
    expect(cells[1]).toHaveClass("d-grid-cell--none");
    expect(cells[2]).toHaveClass("d-grid-cell--hard");
    expect(cells[3]).toHaveClass("d-grid-cell--present");
    expect(cells[6]).toHaveClass("d-grid-cell--proxy");
    // 「つらくて書けない」は症状の列（と体温）をまたぐ
    const tooSick = within(second!).getByText("つらくて書けない");
    expect(tooSick).toHaveAttribute("colspan", "4");
    expect(tooSick).toHaveClass("d-grid-cell--hard");
    // 原文は出さない
    expect(box.querySelector(".d-raw")).toBeNull();
  });

  it("コース外の記録の Day は「—」", async () => {
    renderWith({
      [ENTRIES]: {
        entries: [entry({ course_no: null, day: null })],
        total: 1,
      },
    });
    const box = section("記録");
    await within(box).findByText("コース外");
    const cells = within(bodyRows(box)[0]!).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("—");
  });

  it("受付の時刻の位置に緑の受診日の行を入れる（同じ時刻の記録は線の下）", async () => {
    renderWith({
      [ENTRIES]: {
        entries: [
          entry({ id: 3, recorded_at: "2026-11-09T20:00:00+09:00" }),
          entry({ id: 2, recorded_at: "2026-11-09T09:40:00+09:00" }),
          entry({ id: 1, recorded_at: "2026-11-05T20:00:00+09:00" }),
        ],
        total: 3,
      },
      [VISITS]: {
        visits: [
          visit({ id: 13, created_at: "2026-11-09T09:40:00+09:00" }),
          visit({ id: 12, created_at: "2026-11-09T12:00:00+09:00" }),
        ],
      },
    });
    const box = section("記録");
    const line = await within(box).findByText("受診日 11月9日（月）");
    expect(line).toHaveClass("d-grid-visit-line");
    const rows = bodyRows(box);
    // 1日1件（その日の最初の受付）
    expect(within(box).getAllByText(/^受診日 /)).toHaveLength(1);
    const lineRow = rows.findIndex((r) => r.contains(line));
    expect(lineRow).toBe(1);
    expect(rows[lineRow]!.querySelector("td")).toHaveAttribute(
      "colspan",
      String(within(box).getAllByRole("columnheader").length),
    );
  });

  it("回答の無い記録だけでも表は崩れない（列が無ければ「回答」の1列）", async () => {
    renderWith({
      [ENTRIES]: { entries: [entry({ kind: "too_sick" })], total: 1 },
    });
    const box = section("記録");
    const cell = await within(box).findByText("つらくて書けない");
    expect(cell).toHaveAttribute("colspan", "1");
    expect(
      within(box)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["記録日", "Day", "回答", "自由記載", "代理"]);
  });

  it("表は横にはみ出す時だけ横に送る枠の中", async () => {
    renderWith({ [ENTRIES]: { entries: [entry({})], total: 1 } });
    const table = await within(section("記録")).findByRole("table");
    expect(table.parentElement).toHaveClass("d-grid-scroll");
  });

  it("直近だけを出しているときは総数も出す", async () => {
    renderWith({ [ENTRIES]: { entries: [entry({})], total: 45 } });
    expect(
      await within(section("記録")).findByText(/全 45 件のうち新しい 1 件/),
    ).toBeInTheDocument();
  });

  it("実際の API の応答（fixture）をそのまま並べる", async () => {
    renderWith({ [ENTRIES]: fixtureBody("doctor_patient_entries") as object });
    const box = section("記録");
    await within(box).findAllByRole("row");
    const first = bodyRows(box)[0]!;
    expect(within(first).getByRole("rowheader")).toHaveTextContent(
      "11月9日（月）10:00",
    );
    expect(within(first).getByText("Day14")).toBeInTheDocument();
    expect(within(first).getByText("38.2℃")).toBeInTheDocument();
    expect(within(first).getByText("ある")).toBeInTheDocument();
  });

  it("記録が取れなければ code を出す（他の節は使える）", async () => {
    renderWith({ [ENTRIES]: { entries: "x" } });
    expect(await within(section("記録")).findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
    expect(
      screen.getByRole("button", { name: "＋ コースを追加" }),
    ).toBeInTheDocument();
  });
});

describe("PatientDetail の受診の節", () => {
  it("受付の日時・受付番号・状態と、印刷待ちには「レポートを開く」", async () => {
    renderWith({
      [VISITS]: {
        visits: [
          visit({ id: 13, unprocessed_count: 1 }),
          visit({
            id: 11,
            reception_no: null,
            visit_date: "2026-10-27",
            created_at: "2026-10-27T10:00:00+09:00",
            status: "printed",
            report_available: false,
          }),
          visit({
            id: 9,
            reception_no: null,
            visit_date: "2026-10-13",
            created_at: "2026-10-13T10:00:00+09:00",
            status: "ready",
            report_available: false,
          }),
        ],
      },
    });
    const box = section("受診");
    const rows = (await within(box).findAllByRole("row")).slice(1);
    expect(rows).toHaveLength(3);
    const open = within(rows[0]!);
    expect(open.getByText("A-023")).toBeInTheDocument();
    expect(open.getByText("11月9日（月）09:40")).toBeInTheDocument();
    expect(open.getByText("印刷待ち")).toHaveClass("d-status--ready");
    const report = open.getByRole("link", { name: "レポートを開く" });
    expect(report).toHaveAttribute("href", "/api/doctor/visits/13/report");
    expect(report).toHaveAttribute("target", "_blank");
    expect(open.getByRole("link", { name: "要確認 1件" })).toHaveAttribute(
      "href",
      "/doctor/unprocessed/13",
    );
    const printed = within(rows[1]!);
    expect(printed.getByText("印刷済み")).toBeInTheDocument();
    expect(printed.getByText("10月27日（火）10:00")).toBeInTheDocument();
    expect(printed.queryByRole("link")).toBeNull();
    const expired = within(rows[2]!);
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
    expect(within(rows[0]!).getByText("印刷済み")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("—")).toBeInTheDocument();
  });

  it("受診が取れなければ code を出す", async () => {
    renderWith({ [VISITS]: { visits: [{ id: "x" }] } });
    expect(await within(section("受診")).findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
  });
});
