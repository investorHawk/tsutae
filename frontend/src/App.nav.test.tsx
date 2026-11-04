import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { jsonResponse, mockFetch, type FetchMock } from "./test/fetchMock";
import { PATIENT_STRINGS_FIXTURE } from "./test/patientStringsFixture";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function GoTo({ to }: { to: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" data-testid="go" onClick={() => navigate(to)}>
      go
    </button>
  );
}

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname}</output>;
}

function FromState() {
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "";
  return <output data-testid="from">{from}</output>;
}

describe("患者ルートの定型文", () => {
  it("患者ルートの間を移っても定型文は一度だけ読む", async () => {
    const fetchMock = mockFetch(() => jsonResponse(PATIENT_STRINGS_FIXTURE));
    render(
      <MemoryRouter initialEntries={["/today"]}>
        <App />
        <GoTo to="/history" />
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { level: 1, name: "今日の記録" });
    await userEvent.click(screen.getByTestId("go"));
    await screen.findByRole("heading", { level: 1, name: "これまでの記録" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("医師のログイン", () => {
  it("未ログインで /doctor/login へ移すとき元の経路を state.from に持たせる", async () => {
    mockFetch(() => jsonResponse({ error: "not_logged_in" }, 401));
    render(
      <MemoryRouter initialEntries={["/doctor/patients/P-DEMO0001"]}>
        <App />
        <Routes>
          <Route path="*" element={<FromState />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { level: 1, name: "ログイン" });
    expect(screen.getByTestId("from")).toHaveTextContent(
      "/doctor/patients/P-DEMO0001",
    );
  });

  /** 医師の API の偽物。logout だけ差し替えられる。一覧は空で返す。 */
  function mockDoctorApi(logout: () => Response | Promise<Response>) {
    return mockFetch((url) => {
      if (url === "/api/doctor/logout") {
        return logout();
      }
      if (url === "/api/doctor/skills") {
        return jsonResponse({ skills: [], invalid: [] });
      }
      if (url === "/api/doctor/visits") {
        return jsonResponse({ visits: [] });
      }
      return jsonResponse({ error: "not_found" }, 404);
    });
  }

  function logoutCalls(fetchMock: FetchMock) {
    return fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/doctor/logout",
    );
  }

  function renderDoctorHome() {
    return render(
      <MemoryRouter initialEntries={["/doctor"]}>
        <App />
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("ログアウトで POST /api/doctor/logout し /doctor/login へ", async () => {
    const fetchMock = mockDoctorApi(() => jsonResponse({ ok: true }));
    renderDoctorHome();
    await screen.findByRole("heading", { level: 1, name: "印刷待ち" });
    await userEvent.click(screen.getByRole("button", { name: "ログアウト" }));
    await screen.findByRole("heading", { level: 1, name: "ログイン" });
    const calls = logoutCalls(fetchMock);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]?.method).toBe("POST");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/doctor\/login$/);
  });

  it.each([
    ["500", () => jsonResponse({ error: "boom" }, 500), "boom"],
    ["200 {ok:false}", () => jsonResponse({ ok: false }), "invalid_response"],
    ["200 で本文が空", () => jsonResponse({}), "invalid_response"],
    [
      "通信エラー",
      () => Promise.reject(new TypeError("Failed to fetch")),
      "network_error",
    ],
  ])(
    "ログアウトが失敗（%s）したら医師画面に留まり、エラーを出す",
    async (_label, logout, code) => {
      const fetchMock = mockDoctorApi(logout);
      renderDoctorHome();
      await screen.findByRole("heading", { level: 1, name: "印刷待ち" });
      await userEvent.click(screen.getByRole("button", { name: "ログアウト" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(code);
      expect(screen.getByRole("alert")).toHaveTextContent(
        "ログアウトできませんでした",
      );
      expect(screen.getByTestId("where")).toHaveTextContent(/^\/doctor$/);
      expect(
        screen.getByRole("heading", { level: 1, name: "印刷待ち" }),
      ).toBeInTheDocument();
      expect(logoutCalls(fetchMock)).toHaveLength(1);
    },
  );

  it("ログアウトの失敗後にもう一度押して成功すればログイン画面へ", async () => {
    let fail = true;
    mockDoctorApi(() =>
      fail ? jsonResponse({ error: "boom" }, 500) : jsonResponse({ ok: true }),
    );
    renderDoctorHome();
    await screen.findByRole("heading", { level: 1, name: "印刷待ち" });
    await userEvent.click(screen.getByRole("button", { name: "ログアウト" }));
    await screen.findByRole("alert");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "ログアウト" }));
    await screen.findByRole("heading", { level: 1, name: "ログイン" });
  });

  it("ログアウトが 401（もう切れている）ならログイン画面へ", async () => {
    mockDoctorApi(() => jsonResponse({ error: "not_logged_in" }, 401));
    renderDoctorHome();
    await screen.findByRole("heading", { level: 1, name: "印刷待ち" });
    await userEvent.click(screen.getByRole("button", { name: "ログアウト" }));
    await screen.findByRole("heading", { level: 1, name: "ログイン" });
  });

  it("ログイン後の画面にメニューがある", async () => {
    mockFetch(() => jsonResponse({ skills: [], invalid: [] }));
    render(
      <MemoryRouter initialEntries={["/doctor/settings"]}>
        <App />
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { level: 1, name: "設定を変える" });
    const nav = screen.getByRole("navigation", { name: "医師メニュー" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "印刷待ち" })).toHaveAttribute(
      "href",
      "/doctor",
    );
    expect(screen.getByRole("link", { name: "患者" })).toHaveAttribute(
      "href",
      "/doctor/patients",
    );
  });
});
