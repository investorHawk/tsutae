/**
 * 描画中の例外で画面が真っ白にならない（docs/architecture.md §9 W2b の決定）。
 * 患者側は t("error.generic") だけ、医師側は失敗の知らせを出し、経路が変われば戻る。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ErrorBoundary from "../components/ErrorBoundary";
import { s } from "../pages/patient/testing/fixtures";
import { jsonResponse, mockFetch } from "../test/fetchMock";
import { PATIENT_STRINGS_FIXTURE } from "../test/patientStringsFixture";
import DoctorLayout from "./DoctorLayout";
import DoctorShell from "./DoctorShell";
import PatientLayout from "./PatientLayout";

function Boom(): never {
  throw new TypeError("Cannot read properties of undefined (reading 'map')");
}

function Fine({ name }: { name: string }) {
  return (
    <>
      <h1>{name}</h1>
      <Link to="/a">to a</Link>
      <Link to="/doctor/a">to doctor a</Link>
    </>
  );
}

beforeEach(() => {
  // React は捕まえた例外を console.error に出す（テストの出力を汚さない）
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("shows the fallback instead of a blank screen and nothing of the error", () => {
    const { container } = render(
      <ErrorBoundary fallback={<p>fallback</p>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(container).toHaveTextContent(/^fallback$/);
  });

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary fallback={<p>fallback</p>}>
        <p>child</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("child")).toBeInTheDocument();
    expect(screen.queryByText("fallback")).toBeNull();
  });
});

describe("PatientLayout", () => {
  function renderPatientAt(path: string) {
    mockFetch(() => jsonResponse(PATIENT_STRINGS_FIXTURE));
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<PatientLayout />}>
            <Route path="/boom" element={<Boom />} />
            <Route path="/a" element={<Fine name="page a" />} />
          </Route>
          <Route path="*" element={<Fine name="outside" />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("a page that throws shows only error.generic", async () => {
    const { container } = renderPatientAt("/boom");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(s("error.generic"));
    expect(container.querySelector(".patient-main")).toHaveTextContent(
      new RegExp(`^${s("error.generic")}$`),
    );
  });

  it("a page that works is rendered normally", async () => {
    renderPatientAt("/a");
    expect(
      await screen.findByRole("heading", { name: "page a" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("DoctorLayout / DoctorShell", () => {
  function renderDoctorAt(path: string) {
    mockFetch(() => jsonResponse({ ok: true }));
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/doctor" element={<DoctorLayout />}>
            <Route path="login" element={<Boom />} />
            <Route element={<DoctorShell />}>
              <Route path="boom" element={<Boom />} />
              <Route path="a" element={<Fine name="doctor a" />} />
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  it("a page inside the shell that throws keeps the menu and shows the notice", async () => {
    renderDoctorAt("/doctor/boom");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "画面を表示できませんでした",
    );
    expect(
      screen.getByRole("navigation", { name: "医師メニュー" }),
    ).toBeInTheDocument();
  });

  it("moving to another page clears the notice", async () => {
    renderDoctorAt("/doctor/boom");
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("link", { name: "患者" }));
    // /doctor/patients は無いので何も出ないが、失敗の知らせは消える
    expect(screen.queryByText(/画面を表示できませんでした/)).toBeNull();
  });

  it("the login page (outside the shell) is also caught", async () => {
    renderDoctorAt("/doctor/login");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "画面を表示できませんでした",
    );
  });
});
