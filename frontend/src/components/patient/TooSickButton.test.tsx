/**
 * 「今日はつらくて書けない」の確認。
 * - 未入力（auto）: 確認と「はい」「やめる」を出し、3秒たつと「はい」を自動で押す。
 *   残り秒数は role=status で 3→2→1。「はい」の地は3秒で満ちる（p-countdown-fill）
 * - 入力あり（manual）: today.too_sick_confirm を出し、自動では押さない
 * - タイマーは「やめる」・unmount・disabled で止まる。「はい」は1回の確認で1回だけ
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { s, STRINGS } from "../../pages/patient/testing/fixtures";
import { StaticPatientStringsProvider } from "../../strings/PatientStrings";
import TooSickButton from "./TooSickButton";
import type { ConfirmMode } from "./useTooSickConfirm";

interface Props {
  confirming: ConfirmMode | null;
  disabled?: boolean;
}

function setup({ confirming, disabled = false }: Props) {
  const handlers = {
    onPress: vi.fn(),
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  };
  const ui = (p: Props) => (
    <StaticPatientStringsProvider strings={STRINGS}>
      <TooSickButton
        confirming={p.confirming}
        disabled={p.disabled ?? false}
        sending={false}
        errorKey={null}
        {...handlers}
      />
    </StaticPatientStringsProvider>
  );
  const view = render(ui({ confirming, disabled }));
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  return {
    ...handlers,
    user,
    rerender: (p: Props) => view.rerender(ui(p)),
    unmount: view.unmount,
  };
}

function countdownText(seconds: number): string {
  return s("today.too_sick_countdown").replace("{seconds}", String(seconds));
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

function yesButton() {
  return screen.getByRole("button", { name: s("today.too_sick_confirm_yes") });
}

beforeEach(() => {
  // 偽にするのは秒読みの setInterval だけ。setTimeout まで偽にすると、Testing Library の
  // asyncWrapper（userEvent の後に setTimeout(0) を待つ。vitest の偽の時計は jest として
  // 見えないので進めない）が止まる
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("TooSickButton: closed", () => {
  it("one button; pressing it asks to open the confirm", async () => {
    const { user, onPress, onConfirm } = setup({ confirming: null });
    const button = screen.getByRole("button", {
      name: s("today.too_sick_button"),
    });
    expect(button).toHaveClass("p-button--too-sick");
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    expect(onPress).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("TooSickButton: auto confirm (nothing entered)", () => {
  it("shows the confirm, yes and no, and the button looks pressed", () => {
    setup({ confirming: "auto" });
    expect(
      screen.getByText(s("today.too_sick_confirm_empty")),
    ).toBeInTheDocument();
    expect(screen.queryByText(s("today.too_sick_confirm"))).toBeNull();
    expect(yesButton()).toBeEnabled();
    expect(
      screen.getByRole("button", { name: s("today.too_sick_confirm_no") }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: s("today.too_sick_button") }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("counts down 3, 2, 1 in a status and presses yes after 3 seconds", () => {
    const { onConfirm } = setup({ confirming: "auto" });
    expect(screen.getByRole("status")).toHaveTextContent(countdownText(3));
    advance(1000);
    expect(screen.getByRole("status")).toHaveTextContent(countdownText(2));
    advance(1000);
    expect(screen.getByRole("status")).toHaveTextContent(countdownText(1));
    expect(onConfirm).not.toHaveBeenCalled();
    advance(999);
    expect(onConfirm).not.toHaveBeenCalled();
    advance(1);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    advance(5000);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("the yes button fills from left to right over 3 seconds (hidden from readers)", () => {
    setup({ confirming: "auto" });
    const fill = yesButton().querySelector(".p-countdown-fill");
    expect(fill).not.toBeNull();
    expect(fill).toHaveAttribute("aria-hidden", "true");
    expect(fill).toHaveStyle({ animationDuration: "3s" });
    expect(yesButton()).toHaveClass("p-confirm-yes--auto");
  });

  it("pressing yes before the time confirms once, the timer does not press it again", async () => {
    const { user, onConfirm } = setup({ confirming: "auto" });
    advance(1500);
    await user.click(yesButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
    advance(5000);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("no stops the timer", async () => {
    const { user, onConfirm, onCancel } = setup({ confirming: "auto" });
    advance(1000);
    await user.click(
      screen.getByRole("button", { name: s("today.too_sick_confirm_no") }),
    );
    expect(onCancel).toHaveBeenCalledTimes(1);
    advance(5000);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("closing the confirm (as after no) stops the timer", () => {
    const { onConfirm, rerender } = setup({ confirming: "auto" });
    advance(1000);
    rerender({ confirming: null });
    advance(5000);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("unmounting (leaving the page) stops the timer", () => {
    const { onConfirm, unmount } = setup({ confirming: "auto" });
    advance(1000);
    unmount();
    advance(5000);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disabled stops the timer and hides the countdown", () => {
    const { onConfirm, rerender } = setup({ confirming: "auto" });
    advance(1000);
    rerender({ confirming: "auto", disabled: true });
    expect(screen.queryByText(countdownText(2))).toBeNull();
    advance(5000);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("switching to manual (something was entered) stops the timer", () => {
    const { onConfirm, rerender } = setup({ confirming: "auto" });
    advance(2000);
    rerender({ confirming: "manual" });
    expect(screen.getByText(s("today.too_sick_confirm"))).toBeInTheDocument();
    advance(5000);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("TooSickButton: manual confirm (something entered)", () => {
  it("today.too_sick_confirm, no countdown, never presses yes by itself", async () => {
    const { user, onConfirm } = setup({ confirming: "manual" });
    expect(screen.getByText(s("today.too_sick_confirm"))).toBeInTheDocument();
    expect(screen.queryByText(s("today.too_sick_confirm_empty"))).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(yesButton().querySelector(".p-countdown-fill")).toBeNull();
    advance(10000);
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(yesButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
