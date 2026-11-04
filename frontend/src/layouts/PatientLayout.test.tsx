/** 患者画面の外枠: 登録以外の全画面の下に「症例は全て架空」の注記を出す。 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch } from "../test/fetchMock";
import { PATIENT_STRINGS_FIXTURE } from "../test/patientStringsFixture";
import PatientLayout from "./PatientLayout";

afterEach(() => {
  vi.unstubAllGlobals();
});

const NOTICE = (PATIENT_STRINGS_FIXTURE as Record<string, string>)[
  "app.notice_synthetic"
];

function renderAt(path: string) {
  mockFetch(() => jsonResponse(PATIENT_STRINGS_FIXTURE));
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<PatientLayout />}>
          <Route path="/today" element={<p>today</p>} />
          <Route path="/register" element={<p>register</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("PatientLayout", () => {
  it("shows the synthetic-data notice under the page", async () => {
    renderAt("/today");
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
  });

  it("does not repeat the notice on /register (the page shows it itself)", async () => {
    renderAt("/register");
    expect(await screen.findByText("register")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
  });
});
