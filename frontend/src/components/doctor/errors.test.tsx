import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/http";
import ErrorNote from "./ErrorNote";
import { describeError, describeRegimenError, errorCode } from "./errors";

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

  it("busy は依頼（作業中の書き換え）にも承認・却下にも合う説明", () => {
    expect(describeError("busy")).toContain("書き換え");
    expect(describeError("busy")).toContain("承認・却下");
  });

  it("取り残し・時間切れ（D4 の error_code）にも説明がある", () => {
    expect(describeError("stale_request")).toContain("中断");
    expect(describeError("timeout")).toContain("時間内");
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

describe("describeRegimenError（D4 レジメンの画面）", () => {
  it.each([
    ["token_mismatch", "確認の画面を出した後に値が変わりました"],
    ["ai_values_unconfirmed", "上の値を全て確かめました"],
    ["schedule_locked", "患者がいるため"],
    ["code_taken", "識別名はもう使われています"],
    ["stale", "版が変わりました"],
    ["conflict", "読み直した"],
  ])("%s は採用・保存の場面に合う説明", (code, part) => {
    expect(describeRegimenError(code)).toContain(part);
  });

  it("旧 D4 と同じ code でも、共通の表の説明は変えない", () => {
    expect(describeError("stale")).toContain("依頼");
    expect(describeRegimenError("course_order")).toBe(
      describeError("course_order"),
    );
  });
});
