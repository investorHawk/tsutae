import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/http";
import { errorKeyOf, isNotRegistered, registerErrorKeyOf } from "./patientApi";

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

describe("registerErrorKeyOf", () => {
  const INVALID = "register.number_invalid";

  it.each([400, 404, 422])("%i は番号の誤りのキー", (status) => {
    expect(registerErrorKeyOf(new ApiError(status, "x"), INVALID)).toBe(
      INVALID,
    );
  });

  it("429 は error.too_many_attempts", () => {
    expect(
      registerErrorKeyOf(new ApiError(429, "too_many_attempts"), INVALID),
    ).toBe("error.too_many_attempts");
  });

  it("それ以外は error.generic", () => {
    expect(registerErrorKeyOf(new ApiError(500, "boom"), INVALID)).toBe(
      "error.generic",
    );
    expect(registerErrorKeyOf(new TypeError("x"), INVALID)).toBe(
      "error.generic",
    );
  });
});
