import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { jsonResponse, mockFetch, type FetchMock } from "./test/fetchMock";
import { PATIENT_STRINGS_FIXTURE } from "./test/patientStringsFixture";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname}</output>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Where />
    </MemoryRouter>,
  );
}

/** 患者の定型文と、医師のログイン確認（Skill 一覧）の応答を返す偽の fetch。 */
function mockApi(doctorStatus: number): FetchMock {
  return mockFetch((url) => {
    if (url === "/api/patient/strings") {
      return jsonResponse(PATIENT_STRINGS_FIXTURE);
    }
    if (url === "/api/doctor/skills") {
      return doctorStatus === 200
        ? jsonResponse({ skills: [], invalid: [] })
        : jsonResponse({ error: "not_logged_in" }, doctorStatus);
    }
    return jsonResponse({ error: "not_found" }, 404);
  });
}

async function expectHeading(name: string) {
  expect(
    await screen.findByRole("heading", { level: 1, name }),
  ).toBeInTheDocument();
}

describe("患者ルート", () => {
  it.each([
    ["/register", "はじめての登録"],
    ["/register?pid=P-DEMO0001", "はじめての登録"],
    ["/today", "今日の記録"],
    ["/history", "これまでの記録"],
    ["/visit", "受診の受付"],
  ])("%s は仮ページ（見出しは定型文）", async (path, heading) => {
    const fetchMock = mockApi(401);
    const warn = vi.spyOn(console, "warn");
    renderAt(path);
    await expectHeading(heading);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/patient/strings",
      expect.anything(),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/doctor/skills",
      expect.anything(),
    );
    expect(warn).not.toHaveBeenCalled();
  });

  it("定型文の読み込み前は何も描かない", () => {
    mockFetch(() => new Promise<Response>(() => {}));
    renderAt("/today");
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("/ は /today へ", async () => {
    mockApi(401);
    renderAt("/");
    await expectHeading("今日の記録");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/today$/);
  });

  it("知らない経路は /today へ", async () => {
    mockApi(401);
    renderAt("/no/such/page");
    await expectHeading("今日の記録");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/today$/);
  });
});

describe("医師ルート（ログイン済み）", () => {
  it.each([
    ["/doctor", "印刷待ち"],
    ["/doctor/patients", "患者一覧"],
    ["/doctor/patients/P-DEMO0001", "患者 P-DEMO0001"],
    ["/doctor/settings", "設定を変える"],
    ["/doctor/pipeline/12", "変換ログ"],
    ["/doctor/unprocessed/12", "未処理の記載"],
  ])("%s は仮ページ", async (path, heading) => {
    const fetchMock = mockApi(200);
    renderAt(path);
    await expectHeading(heading);
    expect(screen.getByTestId("where")).toHaveTextContent(
      new RegExp(`^${path}$`),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/patient/strings",
      expect.anything(),
    );
  });

  it("/doctor/login はログイン確認をせずに描く", async () => {
    const fetchMock = mockApi(200);
    renderAt("/doctor/login");
    await expectHeading("ログイン");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("医師の知らない経路は /doctor へ", async () => {
    mockApi(200);
    renderAt("/doctor/no-such");
    await expectHeading("印刷待ち");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/doctor$/);
  });
});

describe("医師ルート（未ログイン）", () => {
  it.each([
    "/doctor",
    "/doctor/patients",
    "/doctor/patients/P-DEMO0001",
    "/doctor/settings",
    "/doctor/pipeline/12",
    "/doctor/unprocessed/12",
  ])("%s は /doctor/login へ", async (path) => {
    mockApi(401);
    renderAt(path);
    await expectHeading("ログイン");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/doctor\/login$/);
  });

  it("ログイン確認中は医師のページを描かない", () => {
    mockFetch(() => new Promise<Response>(() => {}));
    renderAt("/doctor/patients");
    expect(screen.queryByRole("heading", { name: "患者一覧" })).toBeNull();
  });

  it("401 以外の失敗ではページを描く（扱いはページに任せる）", async () => {
    mockApi(500);
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderAt("/doctor/patients");
    await expectHeading("患者一覧");
    expect(screen.getByTestId("where")).toHaveTextContent(
      /^\/doctor\/patients$/,
    );
  });
});
