import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import TwoStepButton from "./TwoStepButton";

function setup(onConfirm: () => Promise<void> | void) {
  render(
    <TwoStepButton
      label="印刷済み"
      prompt="レポートを削除します"
      confirmLabel="削除する"
      onConfirm={onConfirm}
    />,
  );
}

describe("TwoStepButton", () => {
  it("1回目の押下では確かめるだけで実行しない", async () => {
    const onConfirm = vi.fn();
    setup(onConfirm);
    await userEvent.click(screen.getByRole("button", { name: "印刷済み" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText("レポートを削除します")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "削除する" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "印刷済み" })).toBeNull();
  });

  it("やめるで元に戻る", async () => {
    const onConfirm = vi.fn();
    setup(onConfirm);
    await userEvent.click(screen.getByRole("button", { name: "印刷済み" }));
    await userEvent.click(screen.getByRole("button", { name: "やめる" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "印刷済み" }),
    ).toBeInTheDocument();
  });

  it("2回目の押下で実行し、終わるまで押せない", async () => {
    let finish: () => void = () => {};
    const onConfirm = vi.fn(
      () => new Promise<void>((resolve) => (finish = resolve)),
    );
    setup(onConfirm);
    await userEvent.click(screen.getByRole("button", { name: "印刷済み" }));
    await userEvent.click(screen.getByRole("button", { name: "削除する" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "削除する" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "やめる" })).toBeDisabled();
    finish();
    expect(
      await screen.findByRole("button", { name: "印刷済み" }),
    ).toBeEnabled();
  });

  it("実行が失敗しても元に戻る", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    setup(() => Promise.reject(new Error("boom")));
    await userEvent.click(screen.getByRole("button", { name: "印刷済み" }));
    await userEvent.click(screen.getByRole("button", { name: "削除する" }));
    expect(
      await screen.findByRole("button", { name: "印刷済み" }),
    ).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
