/**
 * D6: 同じ画面のまま別の受診へ移ったとき、前の受診の原文を新しい受診の番号の下に残さない
 * （新しい受診の取得が 404 でも）。D5 の受診の切り替えと同じ扱い。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "../../components/doctor/testing";
import Unprocessed from "./Unprocessed";

afterEach(() => {
  vi.unstubAllGlobals();
});

const RAW = "（合成）架空野さんに送ってもらった。";

function GoTo() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/doctor/unprocessed/13")}>
      go
    </button>
  );
}

describe("Unprocessed の受診の切り替え", () => {
  it("移った先が 404 なら not_found だけを出し、前の受診の原文を残さない", async () => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        entries: [
          {
            entry_id: 31,
            record_date: "2026-11-03",
            reason: "unknown_before_honorific",
            text: RAW,
            marks: [],
          },
        ],
      },
    });
    render(
      <MemoryRouter initialEntries={["/doctor/unprocessed/12"]}>
        <Routes>
          <Route
            path="/doctor/unprocessed/:visitId"
            element={<Unprocessed />}
          />
        </Routes>
        <GoTo />
      </MemoryRouter>,
    );
    expect(await screen.findByText(RAW)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "go" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
    expect(screen.getByText(/受診 #13/)).toBeInTheDocument();
    expect(screen.queryByText(RAW)).toBeNull();
  });
});
