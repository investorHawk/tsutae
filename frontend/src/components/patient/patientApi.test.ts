import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/http";
import { errorKeyOf, isNotRegistered } from "./patientApi";

describe("isNotRegistered", () => {
  it("401 と 403 は未登録", () => {
    expect(isNotRegistered(new ApiError(401, "not_registered"))).toBe(true);
    expect(isNotRegistered(new ApiError(403, "forbidden"))).toBe(true);
  });

  it("それ以外は未登録ではない", () => {
    expect(isNotRegistered(new ApiError(404, "unknown_patient"))).toBe(false);
    expect(isNotRegistered(new ApiError(0, "network_error"))).toBe(false);
    expect(isNotRegistered(new Error("x"))).toBe(false);
    expect(isNotRegistered(null)).toBe(false);
  });
});

describe("errorKeyOf", () => {
  it("未登録は error.not_registered、他は error.generic", () => {
    expect(errorKeyOf(new ApiError(403, "forbidden"))).toBe(
      "error.not_registered",
    );
    expect(errorKeyOf(new ApiError(500, "boom"))).toBe("error.generic");
    expect(errorKeyOf(new TypeError("x"))).toBe("error.generic");
  });
});
