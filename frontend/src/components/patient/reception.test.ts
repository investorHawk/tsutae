import { describe, expect, it } from "vitest";
import { RECEPTION_NO_MAX, normalizeReceptionNo } from "./reception";

/**
 * 受付番号はバックエンド（§8b api/visit.py）と同じく NFKC＋前後空白除去の後、
 * 1〜32 字（code point で数える）だけを検査する。文字の種類は制限しない。
 */
describe("normalizeReceptionNo", () => {
  it.each([
    ["A-023", "A-023"],
    ["  a-023 ", "a-023"],
    ["Ａ－０２３", "A-023"], // NFKC で全角は半角に
    ["A﹣023", "A-023"], // SMALL HYPHEN-MINUS（NFKC で "-"）
    ["023", "023"],
    ["受付 12", "受付 12"], // 日本語・途中の空白も契約上有効
    ["Aー023", "Aー023"], // 長音は直さない（日本語の番号を壊さない）
    ["A−023", "A−023"], // NFKC が直さないものはそのまま
    ["　A-023　", "A-023"], // 全角空白の前後除去
    ["A".repeat(32), "A".repeat(32)],
    ["あ".repeat(32), "あ".repeat(32)],
    ["\u{1F600}".repeat(32), "\u{1F600}".repeat(32)], // UTF-16 では64単位
  ])("%j → %j", (input, expected) => {
    expect(normalizeReceptionNo(input)).toBe(expected);
  });

  it.each([
    "",
    "   ",
    "　",
    "A".repeat(33),
    "あ".repeat(33),
    "\u{1F600}".repeat(33),
  ])("%j は不正（null）", (input) => {
    expect(normalizeReceptionNo(input)).toBeNull();
  });

  it("上限は 32", () => {
    expect(RECEPTION_NO_MAX).toBe(32);
  });
});
