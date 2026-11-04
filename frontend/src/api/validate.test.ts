import { describe, expect, it } from "vitest";
import {
  hasNullable,
  isIsoDate,
  isIsoDateTime,
  isOptIsoDate,
  isString,
} from "./validate";

describe("isIsoDate（YYYY-MM-DD・暦に実在する日）", () => {
  it.each(["2026-11-09", "2024-02-29", "2026-12-31", "2026-01-01"])(
    "%s は通る",
    (v) => {
      expect(isIsoDate(v)).toBe(true);
    },
  );

  it.each([
    ["2月30日", "2026-02-30"],
    ["平年の2月29日", "2026-02-29"],
    ["13月", "2026-13-01"],
    ["0月", "2026-00-10"],
    ["0日", "2026-11-00"],
    ["4月31日", "2026-04-31"],
    ["区切りが違う", "2026/11/09"],
    ["桁が足りない", "2026-1-9"],
    ["日時", "2026-11-09T10:00:00+09:00"],
    ["前後に空白", " 2026-11-09"],
  ])("%s（%s）は通らない", (_l, v) => {
    expect(isIsoDate(v)).toBe(false);
  });

  it("文字列でなければ通らない", () => {
    expect(isIsoDate(20261109)).toBe(false);
    expect(isIsoDate(null)).toBe(false);
  });

  it("isOptIsoDate は null・省略を許し、実在しない日は拒む", () => {
    expect(isOptIsoDate(null)).toBe(true);
    expect(isOptIsoDate(undefined)).toBe(true);
    expect(isOptIsoDate("2026-02-30")).toBe(false);
  });
});

describe("isIsoDateTime（ISO 8601・+09:00 付き）", () => {
  it.each([
    "2026-11-09T10:00:00+09:00",
    "2026-11-09T10:00:00.4+09:00",
    "2026-11-09T10:00:00.400+09:00",
    "2026-11-09T23:59:59.123456+09:00",
    "2024-02-29T00:00:00+09:00",
  ])("%s は通る", (v) => {
    expect(isIsoDateTime(v)).toBe(true);
  });

  it.each([
    ["時差が無い", "2026-11-09T10:00:00"],
    ["UTC の Z", "2026-11-09T01:00:00Z"],
    ["+00:00", "2026-11-09T01:00:00+00:00"],
    ["+0900（コロンなし）", "2026-11-09T10:00:00+0900"],
    ["秒が無い", "2026-11-09T10:00+09:00"],
    ["T でなく空白", "2026-11-09 10:00:00+09:00"],
    ["存在しない日", "2026-02-30T10:00:00+09:00"],
    ["24時", "2026-11-09T24:00:00+09:00"],
    ["60分", "2026-11-09T10:60:00+09:00"],
    ["60秒", "2026-11-09T10:00:60+09:00"],
    ["小数秒が7桁", "2026-11-09T10:00:00.1234567+09:00"],
    ["小数点だけ", "2026-11-09T10:00:00.+09:00"],
    ["日付だけ", "2026-11-09"],
    ["任意の文字列", "yesterday"],
  ])("%s（%s）は通らない", (_l, v) => {
    expect(isIsoDateTime(v)).toBe(false);
  });

  it("文字列でなければ通らない", () => {
    expect(isIsoDateTime(Date.now())).toBe(false);
    expect(isIsoDateTime(null)).toBe(false);
  });
});

describe("hasNullable（項目は必須・値は null か型どおり）", () => {
  const check = hasNullable("x", isString);

  it("null と型どおりの値は通る", () => {
    expect(check({ x: null })).toBe(true);
    expect(check({ x: "a" })).toBe(true);
  });

  it("省略・undefined・型違いは通らない", () => {
    expect(check({})).toBe(false);
    expect(check({ x: undefined })).toBe(false);
    expect(check({ x: 1 })).toBe(false);
  });
});
