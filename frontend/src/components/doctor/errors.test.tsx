import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/http";
import ErrorNote from "./ErrorNote";
import { describeError, errorCode } from "./errors";

describe("errorCode", () => {
  it("ApiError はその code", () => {
    expect(errorCode(new ApiError(400, "course_order"))).toBe("course_order");
  });

  it("それ以外は unknown_error", () => {
    expect(errorCode(new Error("x"))).toBe("unknown_error");
    expect(errorCode("x")).toBe("unknown_error");
  });
});

describe("describeError", () => {
  it("知っている code は日本語の説明", () => {
    expect(describeError("course_order")).toBe(
      "実投与日がコース番号の順に増えていません",
    );
  });

  it("知らない code は一般的な説明", () => {
    expect(describeError("something_new")).toBe("処理できませんでした");
  });
});

describe("ErrorNote", () => {
  it("説明と code をそのまま出す", () => {
    render(<ErrorNote code="course_duplicate" />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("同じコース番号がすでにあります");
    expect(alert).toHaveTextContent("course_duplicate");
  });

  it("前置きを付けられる", () => {
    render(<ErrorNote code="network_error" prefix="保存できませんでした" />);
    expect(screen.getByRole("alert")).toHaveTextContent("保存できませんでした");
  });
});
