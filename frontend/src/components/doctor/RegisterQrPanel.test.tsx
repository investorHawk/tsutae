import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RegisterQrPanel from "./RegisterQrPanel";

const PID = "P-AB12CD34";
const URL = `http://localhost:5173/register?pid=${PID}`;

function renderPanel() {
  return render(
    <RegisterQrPanel patientId={PID} url={URL} onClose={vi.fn()} />,
  );
}

describe("RegisterQrPanel", () => {
  it("QR の隣に「登録の番号」と番号を大きく出す", async () => {
    renderPanel();
    const panel = screen.getByRole("region", { name: `${PID} の登録用QR` });
    await within(panel).findByRole("img", { name: `${PID} の登録用QR` });
    const label = within(panel).getByRole("term");
    const value = within(panel).getByRole("definition");
    expect(label).toHaveTextContent("登録の番号");
    expect(value).toHaveTextContent(new RegExp(`^${PID}$`));
    expect(value).toHaveClass("d-qr-number-value");
  });

  it("手で入れるときの案内を出す", async () => {
    renderPanel();
    expect(
      screen.getByText(/ホーム画面のアプリでは、この番号を入れてもらいます/),
    ).toBeInTheDocument();
    await screen.findByRole("img", { name: `${PID} の登録用QR` });
  });

  it("URL の控えは QR の下に残る", async () => {
    renderPanel();
    expect(screen.getByText(URL)).toBeInTheDocument();
    await screen.findByRole("img", { name: `${PID} の登録用QR` });
  });
});
