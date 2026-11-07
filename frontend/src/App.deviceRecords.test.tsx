/**
 * スマホ保存の通し（docs/plan-device-records.md §2）。App を丸ごと描き、IndexedDB は
 * fake-indexeddb、API は実際の FastAPI の応答（src/test/fixtures/api）だけを返す偽物。
 *
 * 番号で登録 → 記録 → 読み直し（再マウント）→ これまでの記録に出る → 受診タブで送る。
 * サーバーへ中身が渡るのは POST /api/visit の1回だけで、送った本文の entries は端末に
 * 保存したものと一致する。受診の本文は実際の 422 と同じく、知らない項目を断る。
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { DeviceEntry, VisitRequest } from "./api/types";
import { callsTo, mockPatientApi } from "./pages/patient/testing/api";
import { s } from "./pages/patient/testing/fixtures";
import { listDeviceEntries, saveDeviceEntry } from "./patient/deviceStore";
import { clearPid, loadPid, savePid } from "./patient/pid";
import { reloadPage } from "./patient/reload";
import { apiFixture, fixtureBody } from "./test/apiFixtures";
import { jsonResponse, type FetchMock } from "./test/fetchMock";

vi.mock("./patient/reload", () => ({ reloadPage: vi.fn() }));

const PID = "P-DEMO0001";
const OTHER_PID = "P-OTHER001";
const RECEPTION = "A-023";
const FREE_TEXT = "free text sample for the visit";
const TEMPERATURE = "38.2";
const MARK_URL = `/api/patient/${PID}/record-marks`;
const VISIT_URL = "/api/visit";
const SKILL = "regimen-folfox@1";

interface FixtureEntry {
  answers: Record<string, unknown>[];
}

/** 実際の API に通った本文（scripts/dump_api_device.py）。形の比べる相手。 */
const ACCEPTED = apiFixture("visit_with_entries").request as {
  reception_no: string;
  entries: (Record<string, unknown> & FixtureEntry)[];
};
const WINDOW = fixtureBody("patient_visit_window") as {
  start: string;
  end: string;
};

interface DemoSamples {
  entries: DeviceEntry[];
}

function questionText(key: string): string {
  const body = fixtureBody("patient_questions") as {
    questions: { key: string; text: string }[];
  };
  const found = body.questions.find((q) => q.key === key);
  if (!found) {
    throw new Error(`fixture に質問 ${key} が無い`);
  }
  return found.text;
}

function keysOf(value: object): string[] {
  return Object.keys(value).sort();
}

/** VisitEntryIn と同じ検査（知らない項目・足りない項目・範囲の外は 422）。 */
function isAcceptable(body: VisitRequest): boolean {
  const entryKeys = keysOf(ACCEPTED.entries[0]!);
  const answerKeys = keysOf(ACCEPTED.entries[0]!.answers[0]!);
  return (body.entries ?? []).every(
    (entry) =>
      keysOf(entry).join() === entryKeys.join() &&
      entry.answers.every((a) => keysOf(a).join() === answerKeys.join()) &&
      WINDOW.start <= entry.record_date &&
      entry.record_date <= WINDOW.end,
  );
}

/** 実際の応答の fixture だけを返す偽の API。受診の後は受診日が1件増える。 */
function mockRealApi(demoConfig = "patient_demo_config_other"): FetchMock {
  let visited = false;
  const fixture = (name: string, status = 200) =>
    jsonResponse(fixtureBody(name), status);
  return mockPatientApi({
    strings: () => fixture("patient_strings"),
    register: () => fixture("patient_register"),
    questions: () => fixture("patient_questions"),
    recordMark: () => fixture("patient_record_mark"),
    pushConfig: () => fixture("patient_push_config"),
    demoConfig: () => fixture(demoConfig),
    demoEntries: () => fixture("patient_demo_entries"),
    visitWindow: () => fixture("patient_visit_window"),
    visitDays: () =>
      visited ? fixture("patient_visit_days") : jsonResponse({ visits: [] }),
    visit: (body) => {
      if (!isAcceptable(body as VisitRequest)) {
        return fixture("visit_entries_invalid", 422);
      }
      visited = true;
      return fixture("visit_with_entries");
    },
  });
}

function openApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

/** ホーム画面のアイコンから開き直す: 画面の state は消え、端末の保存だけが残る。 */
function reopenApp(path: string) {
  cleanup();
  return openApp(path);
}

async function title(key: string) {
  return screen.findByRole("heading", { level: 1, name: new RegExp(s(key)) });
}

async function goToTab(key: string) {
  await userEvent.click(screen.getByRole("link", { name: s(key) }));
}

async function choose(questionKey: string, answerKey: string) {
  const group = await screen.findByRole("group", {
    name: questionText(questionKey),
  });
  await userEvent.click(
    within(group).getByRole("button", { name: s(answerKey) }),
  );
}

async function registerWithNumber() {
  await userEvent.type(
    await screen.findByRole("textbox", { name: s("register.number_label") }),
    PID,
  );
  await userEvent.click(
    screen.getByRole("button", { name: s("register.number_submit") }),
  );
}

async function recordEverything() {
  await choose("diarrhea", "answer.hard");
  await choose("fever", "answer.measured");
  await userEvent.type(
    screen.getByRole("textbox", { name: s("temperature.label") }),
    TEMPERATURE,
  );
  await userEvent.type(
    screen.getByRole("textbox", { name: s("today.free_text_label") }),
    FREE_TEXT,
  );
  await userEvent.click(
    screen.getByRole("button", { name: s("today.submit") }),
  );
  await screen.findByText(s("today.saved"));
}

async function recordTooSick() {
  await userEvent.click(
    screen.getByRole("button", { name: s("today.too_sick_button") }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: s("today.too_sick_confirm_yes") }),
  );
  await screen.findByText(s("today.too_sick_done"));
}

async function sendAtVisit() {
  await userEvent.type(
    await screen.findByRole("textbox", { name: s("visit.reception_label") }),
    RECEPTION,
  );
  await userEvent.click(
    screen.getByRole("button", { name: s("visit.submit") }),
  );
  await screen.findByText(s("visit.done"));
}

function oldEntry(over: Partial<DeviceEntry>): DeviceEntry {
  return {
    pid: PID,
    client_entry_id: "00000000-0000-4000-8000-000000000000",
    recorded_at: "2026-11-02T08:10:00.000000+09:00",
    record_date: "2026-11-02",
    kind: "free_text",
    by_proxy: false,
    skill_version: SKILL,
    answers: [],
    free_text: "older note",
    ...over,
  };
}

/** 範囲の中の前の記録・範囲の外の記録・別の患者の記録。 */
const IN_WINDOW = oldEntry({
  client_entry_id: "00000000-0000-4000-8000-000000000001",
  free_text: "older note in the window",
});
const BEFORE_WINDOW = oldEntry({
  client_entry_id: "00000000-0000-4000-8000-000000000002",
  recorded_at: "2026-10-12T08:10:00.000000+09:00",
  record_date: "2026-10-12",
  free_text: "older note before the window",
});
const OTHER_PATIENT = oldEntry({
  pid: OTHER_PID,
  client_entry_id: "00000000-0000-4000-8000-000000000003",
  free_text: "note of another patient",
});

/** 端末の記録 → 受付の形（pid と質問の文の写しを外す）。実装を通さず、ここで独立に作る。 */
function expectedVisitEntry(entry: DeviceEntry): Record<string, unknown> {
  return {
    client_entry_id: entry.client_entry_id,
    recorded_at: entry.recorded_at,
    record_date: entry.record_date,
    kind: entry.kind,
    by_proxy: entry.by_proxy,
    skill_version: entry.skill_version,
    answers: entry.answers.map((a) => ({
      question_key: a.question_key,
      value: a.value,
      temperature: a.temperature,
    })),
    free_text: entry.free_text,
  };
}

function byId<T extends { client_entry_id: string }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) =>
    a.client_entry_id.localeCompare(b.client_entry_id),
  );
}

/** 受診の本文以外の全ての要求（経路と本文）に、記録の中身が無いこと。 */
function expectNoContentOutsideTheVisit(fetchMock: FetchMock) {
  const others = JSON.stringify(
    fetchMock.mock.calls
      .filter(([url]) => String(url) !== VISIT_URL)
      .map(([url, init]) => [String(url), init?.body ?? null]),
  );
  for (const text of [
    FREE_TEXT,
    IN_WINDOW.free_text!,
    TEMPERATURE,
    "diarrhea",
    "answers",
    "free_text",
  ]) {
    expect(others).not.toContain(text);
  }
}

/** 端末には、印の応答の時刻と質問の文の写しで保存される。 */
async function expectSavedToday() {
  const mark = fixtureBody("patient_record_mark") as {
    record_date: string;
    recorded_at: string;
  };
  const saved = await listDeviceEntries(PID);
  const today = saved.filter((e) => e.record_date === mark.record_date);
  expect(today.map((e) => e.recorded_at)).toEqual([
    mark.recorded_at,
    mark.recorded_at,
  ]);
  expect(today.map((e) => e.kind).sort()).toEqual(["mixed", "too_sick"]);
  const written = today.find((e) => e.kind === "mixed")!;
  expect(written).toMatchObject({
    pid: PID,
    skill_version: SKILL,
    free_text: FREE_TEXT,
  });
  expect(written.answers).toEqual([
    {
      question_key: "diarrhea",
      value: "hard",
      temperature: null,
      question_text: questionText("diarrhea"),
    },
    {
      question_key: "fever",
      value: "measured",
      temperature: Number(TEMPERATURE),
      question_text: questionText("fever"),
    },
  ]);
}

/** これまでの記録に今日の記録が出て、別の患者の記録は出ない。 */
async function expectHistory(rowCount: number) {
  const list = await screen.findByRole("list", { name: s("history.title") });
  expect(within(list).getAllByRole("listitem")).toHaveLength(rowCount);
  expect(within(list).getByText(FREE_TEXT)).toBeInTheDocument();
  expect(within(list).getByText(IN_WINDOW.free_text!)).toBeInTheDocument();
  expect(within(list).queryByText(OTHER_PATIENT.free_text!)).toBeNull();
}

/** 送った本文は端末の範囲内の記録そのまま。範囲外・別の患者の分・質問の文の写しは入らない。 */
async function expectVisitBody(fetchMock: FetchMock) {
  const stored = await listDeviceEntries(PID);
  const inWindow = stored.filter(
    (e) => e.client_entry_id !== BEFORE_WINDOW.client_entry_id,
  );
  expect(inWindow).toHaveLength(3);
  const visits = callsTo(fetchMock, "POST", VISIT_URL) as VisitRequest[];
  expect(visits).toHaveLength(1);
  const body = visits[0]!;
  expect(body.reception_no).toBe(RECEPTION);
  expect(byId(body.entries ?? [])).toEqual(
    byId(inWindow).map(expectedVisitEntry),
  );
  const raw = JSON.stringify(body);
  expect(raw).not.toContain(OTHER_PATIENT.free_text!);
  expect(raw).not.toContain(BEFORE_WINDOW.free_text!);
  expect(raw).not.toContain("question_text");
}

beforeEach(() => {
  clearPid();
  vi.mocked(reloadPage).mockClear();
});

afterEach(() => {
  clearPid();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("device records, from recording to the visit", () => {
  it("records on the phone, survives reopening, and leaves only with the visit", async () => {
    await saveDeviceEntry(IN_WINDOW);
    await saveDeviceEntry(BEFORE_WINDOW);
    await saveDeviceEntry(OTHER_PATIENT);
    const fetchMock = mockRealApi();

    // 番号で登録する（Safari ではなくホーム画面のアプリの中）
    openApp("/");
    await registerWithNumber();
    expect(vi.mocked(reloadPage)).toHaveBeenCalledTimes(1);
    expect(loadPid()).toBe(PID);
    expect(callsTo(fetchMock, "POST", "/api/patient/register")).toEqual([
      { pid: PID },
    ]);

    // 記録する: 全部入りの1件と、続けて「つらくて書けない」
    reopenApp("/today");
    await title("today.title");
    await recordEverything();
    expect(screen.getByRole("alert").textContent).toBe(
      s("fixed_rule.fever_38"),
    );
    await userEvent.click(
      screen.getByRole("button", { name: s("today.add_more") }),
    );
    await recordTooSick();

    // サーバーへ送ったのは本文のない印だけで、中身は端末にある
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([
      undefined,
      undefined,
    ]);
    expect(callsTo(fetchMock, "POST", VISIT_URL)).toEqual([]);
    expectNoContentOutsideTheVisit(fetchMock);
    await expectSavedToday();

    // 開き直しても、これまでの記録に出る（今日の2件・範囲内・範囲外）
    reopenApp("/today");
    await title("today.title");
    await goToTab("nav.history");
    await title("history.title");
    await expectHistory(4);

    // 受診タブで送る。中身が出ていくのは受診の本文だけ
    await goToTab("nav.visit");
    await title("visit.title");
    await sendAtVisit();
    expect(screen.queryByRole("alert")).toBeNull();
    await expectVisitBody(fetchMock);
    expectNoContentOutsideTheVisit(fetchMock);

    // 送った後も端末に残り、これまでの記録に受診日の区切りが増える
    const stored = await listDeviceEntries(PID);
    reopenApp("/history");
    await expectHistory(5);
    expect(await listDeviceEntries(PID)).toEqual(stored);
    expect(await listDeviceEntries(OTHER_PID)).toEqual([OTHER_PATIENT]);
  });

  it("sends the samples once, however many times they are added", async () => {
    savePid(PID);
    const fetchMock = mockRealApi("patient_demo_config");
    const samples = (fixtureBody("patient_demo_entries") as DemoSamples)
      .entries;
    const inWindow = samples.filter(
      (e) => WINDOW.start <= e.record_date && e.record_date <= WINDOW.end,
    );
    expect(inWindow.length).toBeGreaterThan(0);

    openApp("/settings");
    await title("settings.title");
    const add = await screen.findByRole("button", {
      name: s("demo.add_entries"),
    });
    await userEvent.click(add);
    await screen.findByText(s("demo.added"));
    await userEvent.click(add);
    await screen.findByText(s("demo.added"));
    expect(await listDeviceEntries(PID)).toHaveLength(samples.length);

    reopenApp("/visit");
    await sendAtVisit();
    const visits = callsTo(fetchMock, "POST", VISIT_URL) as VisitRequest[];
    expect(visits).toHaveLength(1);
    expect(byId(visits[0]!.entries ?? [])).toEqual(
      byId(inWindow).map(expectedVisitEntry),
    );
  });
});
