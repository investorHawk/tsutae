/** iPhone のブラウザでは、全ての患者画面で「ホーム画面に追加」の案内だけを出す（§5.8）。 */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ENTRIES, PID, s, STRINGS } from "../pages/patient/testing/fixtures";
import { saveDeviceEntry } from "../patient/deviceStore";
import { clearPid, loadPid } from "../patient/pid";
import { jsonResponse, mockFetch, type FetchMock } from "../test/fetchMock";

const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const ANDROID =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";

const STUBBED = ["userAgent", "standalone"];

function setNavigator(name: string, value: unknown) {
  Object.defineProperty(navigator, name, { configurable: true, value });
}

function mockApi(): FetchMock {
  return mockFetch((url) =>
    url === "/api/patient/strings"
      ? jsonResponse(STRINGS)
      : jsonResponse({ error: "not_logged_in" }, 401),
  );
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

function urlsOf(mock: FetchMock): string[] {
  return mock.mock.calls.map(([input]) => String(input));
}

beforeEach(() => {
  clearPid();
});

afterEach(() => {
  for (const name of STUBBED) {
    delete (navigator as unknown as Record<string, unknown>)[name];
  }
  clearPid();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("iPhone Safari", () => {
  beforeEach(() => setNavigator("userAgent", IPHONE));

  it.each([
    "/register?pid=P-DEMO0001",
    "/today",
    "/history",
    "/visit",
    "/settings",
  ])("%s shows only the guide", async (path) => {
    const fetchMock = mockApi();
    renderAt(path);
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: s("guide.title"),
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(urlsOf(fetchMock)).toEqual(["/api/patient/strings"]);
  });

  it("lists the steps in order", async () => {
    mockApi();
    renderAt("/today");
    const list = await screen.findByRole("list");
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      s("guide.step_share"),
      s("guide.step_add"),
      s("guide.step_open"),
      s("guide.step_number"),
    ]);
  });

  it("shows the number from the URL large, and does not register or save it", async () => {
    const fetchMock = mockApi();
    renderAt("/register?pid=P-DEMO0001");
    const number = await screen.findByText("P-DEMO0001");
    expect(number).toHaveClass("p-guide-number-value");
    expect(screen.getByText(s("register.number_label"))).toBeInTheDocument();
    expect(loadPid()).toBeNull();
    expect(urlsOf(fetchMock)).not.toContain("/api/patient/register");
  });

  it("the number also shows on other screens that have it", async () => {
    mockApi();
    renderAt("/today?pid=P-DEMO0001");
    expect(await screen.findByText("P-DEMO0001")).toBeInTheDocument();
  });

  it.each([
    ["no pid", "/register"],
    ["malformed", "/register?pid=not-a-number"],
    ["markup", "/register?pid=%3Cb%3EP-DEMO0001%3C/b%3E"],
  ])("%s: no number block", async (_label, path) => {
    mockApi();
    const { container } = renderAt(path);
    await screen.findByRole("heading", { level: 1, name: s("guide.title") });
    expect(container.querySelector(".p-guide-number-value")).toBeNull();
    expect(screen.queryByText(s("register.number_label"))).toBeNull();
  });

  it("keeps the synthetic notice", async () => {
    mockApi();
    renderAt("/register?pid=P-DEMO0001");
    expect(
      await screen.findByText(s("app.notice_synthetic")),
    ).toBeInTheDocument();
  });

  it("does not show the records already on the phone", async () => {
    await saveDeviceEntry(ENTRIES[0]!);
    window.localStorage.setItem("tsutae.pid", PID);
    const fetchMock = mockApi();
    renderAt("/history");
    await screen.findByRole("heading", { level: 1, name: s("guide.title") });
    expect(screen.queryByText(s("history.too_sick"))).toBeNull();
    expect(urlsOf(fetchMock)).toEqual(["/api/patient/strings"]);
  });

  it("the doctor screens are not affected", async () => {
    mockFetch(() => jsonResponse({ error: "not_logged_in" }, 401));
    renderAt("/doctor/login");
    expect(
      await screen.findByRole("heading", { level: 1, name: "ログイン" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(s("guide.title"))).toBeNull();
  });
});

describe("iPhone home screen app", () => {
  it("shows the screen, not the guide", async () => {
    setNavigator("userAgent", IPHONE);
    setNavigator("standalone", true);
    mockApi();
    renderAt("/settings");
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: s("settings.title"),
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText(s("guide.title"))).toBeNull();
  });
});

describe("other browsers", () => {
  it("a desktop browser sees no guide and no suggestion", async () => {
    mockApi();
    renderAt("/settings");
    await screen.findByRole("heading", {
      level: 1,
      name: s("settings.title"),
    });
    expect(screen.queryByText(s("guide.title"))).toBeNull();
    expect(screen.queryByText(s("guide.suggest"))).toBeNull();
  });

  it("an Android browser can use the screens and is advised to add to the home screen", async () => {
    setNavigator("userAgent", ANDROID);
    mockApi();
    renderAt("/settings");
    await screen.findByRole("heading", {
      level: 1,
      name: s("settings.title"),
    });
    expect(screen.getByText(s("guide.suggest"))).toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });
});
