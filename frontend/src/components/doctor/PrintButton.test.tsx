/**
 * D3 の「印刷」。レポートは CSP で script が動かないので、同じオリジンの非表示 iframe に
 * 読み込み、load の後に親から contentWindow.print() を呼ぶ。開けなければ別タブのリンクへ。
 * （jsdom は iframe の load を自分では起こさないので fireEvent.load で起こす）
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import PrintButton, { PRINT_HINT, PRINT_LOAD_TIMEOUT_MS } from "./PrintButton";

const URL_ = "/api/doctor/visits/12/report";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function frame(): HTMLIFrameElement {
  const el = document.querySelector("iframe");
  if (!el) {
    throw new Error("iframe が無い");
  }
  return el;
}

function stubPrint(impl: () => void = () => {}) {
  const win = frame().contentWindow;
  if (!win) {
    throw new Error("contentWindow が無い");
  }
  const print = vi.fn(impl);
  win.print = print;
  return print;
}

describe("PrintButton", () => {
  it("押すまで iframe を作らない。別タブで開くリンクは持たない（ReportLink を並べる）", () => {
    render(<PrintButton url={URL_} />);
    expect(document.querySelector("iframe")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("案内の一行はボタンに付けない（印刷待ちの表の上に1回だけ出す。D2-1）", () => {
    render(<PrintButton url={URL_} />);
    expect(screen.queryByText(PRINT_HINT)).toBeNull();
    expect(PRINT_HINT).toBe(
      "印刷ダイアログが開きます。開かなければ『レポートを開く』から ⌘P",
    );
  });

  it("押すと同じオリジンの非表示 iframe に読み込み、load の後に print を呼ぶ", async () => {
    render(<PrintButton url={URL_} />);
    await userEvent.click(screen.getByRole("button", { name: "印刷" }));
    const el = frame();
    expect(el).toHaveAttribute("src", URL_);
    expect(el).toHaveClass("d-print-frame");
    expect(el).toHaveAttribute("aria-hidden", "true");
    const print = stubPrint();
    expect(print).not.toHaveBeenCalled();
    fireEvent.load(el);
    expect(print).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("もう一度押すと読み直して、もう一度 print を呼ぶ", async () => {
    render(<PrintButton url={URL_} />);
    const button = screen.getByRole("button", { name: "印刷" });
    await userEvent.click(button);
    const first = frame();
    stubPrint();
    fireEvent.load(first);
    await userEvent.click(button);
    const second = frame();
    expect(second).not.toBe(first);
    const print = stubPrint();
    fireEvent.load(second);
    expect(print).toHaveBeenCalledTimes(1);
    expect(document.querySelectorAll("iframe")).toHaveLength(1);
  });

  it("print が投げたら、別タブで開く案内に戻す", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<PrintButton url={URL_} />);
    await userEvent.click(screen.getByRole("button", { name: "印刷" }));
    stubPrint(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    fireEvent.load(frame());
    expect(screen.getByRole("alert")).toHaveTextContent(
      "印刷ダイアログを開けませんでした。『レポートを開く』から ⌘P",
    );
  });

  it("読み込みが終わらなければ、時間切れで別タブの案内を出す", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<PrintButton url={URL_} />);
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await u.click(screen.getByRole("button", { name: "印刷" }));
    const print = stubPrint();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRINT_LOAD_TIMEOUT_MS);
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "印刷ダイアログを開けませんでした",
    );
    fireEvent.load(frame());
    expect(print).not.toHaveBeenCalled();
  });
});
