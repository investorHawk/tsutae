import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatusBadge from "./StatusBadge";

describe("StatusBadge", () => {
  it.each([
    ["generating", "生成中"],
    ["ready", "印刷待ち"],
    ["printed", "印刷済み"],
    ["failed", "失敗"],
  ] as const)("%s は「%s」", (status, label) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(label);
    expect(badge).toHaveClass("d-status", `d-status--${status}`);
  });
});
