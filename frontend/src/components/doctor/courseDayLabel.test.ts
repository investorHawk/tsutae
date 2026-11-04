import { describe, expect, it } from "vitest";
import { courseDayLabel } from "./courseDayLabel";

describe("courseDayLabel", () => {
  it("コースと Day", () => {
    expect(courseDayLabel(3, 14)).toBe("第3コース Day14");
  });

  it("Day が無ければコースだけ、コースが無ければ null", () => {
    expect(courseDayLabel(3, null)).toBe("第3コース");
    expect(courseDayLabel(null, null)).toBeNull();
    expect(courseDayLabel(null, 5)).toBeNull();
  });
});
