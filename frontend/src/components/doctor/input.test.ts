import { describe, expect, it } from "vitest";
import { ApiError, INVALID_RESPONSE, isApiError } from "../../api/http";
import { listOf, parseVisitId, safeDoctorPath } from "./input";

describe("parseVisitId", () => {
  it.each([
    ["12", 12],
    ["1", 1],
  ])("%s → %d", (value, expected) => {
    expect(parseVisitId(value)).toBe(expected);
  });

  it.each([
    undefined,
    "",
    "0",
    "012",
    "-1",
    "1.5",
    "abc",
    "12a",
    "99999999999",
  ])("%s は null", (value) => {
    expect(parseVisitId(value)).toBeNull();
  });
});

describe("listOf", () => {
  it("配列の要素を返す", () => {
    expect(listOf({ visits: [{ id: 1 }, { id: 2 }] }, "visits")).toEqual([
      { id: 1 },
      { id: 2 },
    ]);
    expect(listOf({ visits: [] }, "visits")).toEqual([]);
  });

  it.each([
    undefined,
    null,
    "x",
    [],
    { ok: true },
    { visits: "x" },
    { visits: null },
    { visits: [{ id: 1 }, null] },
    { visits: [{ id: 1 }, 3] },
    { visits: [[]] },
  ])("%o は invalid_response（0件にしない）", (body) => {
    expect(() => listOf(body, "visits")).toThrow(ApiError);
    try {
      listOf(body, "visits");
    } catch (err) {
      expect(isApiError(err) && err.code).toBe(INVALID_RESPONSE);
    }
  });

  it("要素の検査に合わなければ invalid_response", () => {
    const isItem = (v: Record<string, unknown>): boolean =>
      typeof v.id === "number";
    expect(listOf({ visits: [{ id: 1 }] }, "visits", isItem)).toEqual([
      { id: 1 },
    ]);
    expect(() =>
      listOf({ visits: [{ id: 1 }, { id: "2" }] }, "visits", isItem),
    ).toThrow(ApiError);
  });
});

describe("safeDoctorPath", () => {
  it.each([
    [{ from: "/doctor/settings" }, "/doctor/settings"],
    [{ from: "/doctor" }, "/doctor"],
    [{ from: "/doctor/login" }, "/doctor"],
    [{ from: "/today" }, "/doctor"],
    [{ from: "/doctorx" }, "/doctor"],
    [{ from: "https://example.invalid/doctor" }, "/doctor"],
    [{ from: 1 }, "/doctor"],
    [null, "/doctor"],
  ])("%o → %s", (state, expected) => {
    expect(safeDoctorPath(state)).toBe(expected);
  });
});
