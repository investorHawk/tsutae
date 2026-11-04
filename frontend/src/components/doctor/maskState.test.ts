import { describe, expect, it } from "vitest";
import type { MaskCheckResponse } from "../../api/types";
import { unprocessedItemStub } from "../../test/doctorStubs";
import {
  initialMaskState,
  initialMaskStates,
  saveEntries,
  sendCount,
  withCheck,
  withConfirmed,
  withSend,
  withSpans,
} from "./maskState";

const CHECK: MaskCheckResponse = {
  entry_id: 38,
  masked_text: "磯鷲さんにもらった漢方",
  suspects: [{ start: 0, end: 4, rule: "unknown_before_honorific" }],
  reason: "unknown_before_honorific",
  sendable: false,
  confirmable: true,
};

describe("initialMaskState", () => {
  it("保存済みの伏せ字が無ければ、疑われた区間を伏せて「送らない」", () => {
    const item = unprocessedItemStub({ marks: [{ start: 0, end: 4 }] });
    expect(initialMaskState(item)).toEqual({
      send: false,
      spans: [{ start: 0, end: 4 }],
      confirmed: false,
      check: null,
    });
  });

  it("保存済みの伏せ字があれば、その区間と確かめで「送る」", () => {
    const item = unprocessedItemStub({
      marks: [{ start: 0, end: 4 }],
      doctor_mask: { spans: [{ start: 0, end: 2 }], confirmed_clear: true },
    });
    expect(initialMaskState(item)).toEqual({
      send: true,
      spans: [{ start: 0, end: 2 }],
      confirmed: true,
      check: null,
    });
  });

  it("記録ごとの対応表を作る", () => {
    const states = initialMaskStates([
      unprocessedItemStub({ entry_id: 1 }),
      unprocessedItemStub({ entry_id: 2 }),
    ]);
    expect(Object.keys(states)).toEqual(["1", "2"]);
  });
});

describe("状態の更新", () => {
  const base = initialMaskState(unprocessedItemStub());

  it("区間を変えると確かめた結果と印を捨てる", () => {
    const checked = withConfirmed(withCheck(base, CHECK), true);
    expect(checked.confirmed).toBe(true);
    const next = withSpans(checked, [{ start: 0, end: 2 }]);
    expect(next.check).toBeNull();
    expect(next.confirmed).toBe(false);
    expect(checked.check).toBe(CHECK); // 引数は変えない
  });

  it("同じ区間なら同じ状態を返す", () => {
    expect(withSpans(base, [...base.spans])).toBe(base);
  });

  it("確かめて送れない結果なら印を外す", () => {
    const confirmed = withConfirmed(base, true);
    expect(
      withCheck(confirmed, { ...CHECK, confirmable: false }).confirmed,
    ).toBe(false);
  });
});

describe("saveEntries", () => {
  it("区間と印だけを送る（送らない記録は区間を空に）", () => {
    const a = unprocessedItemStub({ entry_id: 1 });
    const b = unprocessedItemStub({ entry_id: 2 });
    const states = {
      1: withConfirmed(withSend(initialMaskState(a), true), true),
      2: withConfirmed(initialMaskState(b), true),
    };
    expect(saveEntries([a, b], states)).toEqual([
      { entry_id: 1, send: true, spans: [], confirmed_clear: true },
      { entry_id: 2, send: false, spans: [], confirmed_clear: false },
    ]);
    expect(sendCount(states)).toBe(1);
  });
});
