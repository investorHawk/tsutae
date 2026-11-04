import { render, screen } from "@testing-library/react";
import QRCode from "qrcode";
import { describe, expect, it } from "vitest";
import QrImage, { QR_OPTIONS, svgDataUrl } from "./QrImage";

const URL_A = "http://localhost:5173/register?pid=P-AB12CD34";
const URL_B = "http://localhost:5173/register?pid=P-ZZ99ZZ99";

describe("QrImage", () => {
  it("register_url の QR を SVG の data URL で描く", async () => {
    render(<QrImage url={URL_A} label="P-AB12CD34 の登録用QR" />);
    const img = await screen.findByRole("img", {
      name: "P-AB12CD34 の登録用QR",
    });
    const src = img.getAttribute("src") ?? "";
    expect(src.startsWith("data:image/svg+xml")).toBe(true);
    const svg = decodeURIComponent(src.slice(src.indexOf(",") + 1));
    expect(svg).toContain("<svg");
    expect(svg).toContain("<path");
    expect(src).toBe(svgDataUrl(await QRCode.toString(URL_A, QR_OPTIONS)));
  });

  it("URL が違えば違う QR になる", async () => {
    const { unmount } = render(<QrImage url={URL_A} label="a" />);
    const a = (await screen.findByRole("img", { name: "a" })).getAttribute(
      "src",
    );
    unmount();
    render(<QrImage url={URL_B} label="b" />);
    const b = (await screen.findByRole("img", { name: "b" })).getAttribute(
      "src",
    );
    expect(a).not.toBe(b);
  });

  it("URL を文字でも出す（読み取れないときの控え）", async () => {
    render(<QrImage url={URL_A} label="a" />);
    expect(screen.getByText(URL_A)).toBeInTheDocument();
    await screen.findByRole("img", { name: "a" });
  });

  it("描けない（長すぎる）ときは画像を出さず、その旨を出す", async () => {
    render(<QrImage url={"x".repeat(8000)} label="too-long" />);
    expect(
      await screen.findByText("QR を描けませんでした"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
