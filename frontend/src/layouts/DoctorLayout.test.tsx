/** 医師画面の外枠: ログイン画面を含む全ての医師画面の上端に「症例は全て架空」の注記を出す。 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import DoctorLayout, { DOCTOR_SYNTHETIC_NOTICE } from "./DoctorLayout";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/doctor" element={<DoctorLayout />}>
          <Route path="login" element={<p>login</p>} />
          <Route index element={<p>visits</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("DoctorLayout", () => {
  it.each([
    ["/doctor/login", "login"],
    ["/doctor", "visits"],
  ])("%s にも架空の注記を出す", (path, body) => {
    renderAt(path);
    expect(screen.getByText(body)).toBeInTheDocument();
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(DOCTOR_SYNTHETIC_NOTICE);
  });

  it("注記の文は「症例は全て架空」を含む（患者画面・レポートと同じ言い方）", () => {
    expect(DOCTOR_SYNTHETIC_NOTICE).toContain("症例は全て架空");
  });

  it("注記はページの本文より前に置く（スクロールしても上端に残す）", () => {
    renderAt("/doctor");
    const note = screen.getByRole("note");
    const body = screen.getByText("visits");
    expect(
      note.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(note).toHaveClass("doctor-synthetic");
  });
});
