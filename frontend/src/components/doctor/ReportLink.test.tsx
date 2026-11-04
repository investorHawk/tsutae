import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ReportLink from "./ReportLink";

describe("ReportLink", () => {
  it("その受診のレポートを別のタブで開く", () => {
    render(<ReportLink visitId={12} />);
    const link = screen.getByRole("link", { name: "レポートを開く" });
    expect(link).toHaveAttribute("href", "/api/doctor/visits/12/report");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
