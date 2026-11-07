import { describe, expect, it } from "vitest";
import type { DeviceEntry, VisitEntry, VisitRequest } from "../api/types";
import { apiFixture } from "../test/apiFixtures";
import { entriesInWindow, toVisitEntry } from "./visitEntries";

const WINDOW = { start: "2026-10-13", end: "2026-11-09" };

function entry(id: string, recordDate: string): DeviceEntry {
  return {
    pid: "P-DEMO0001",
    client_entry_id: id,
    recorded_at: `${recordDate}T20:00:00.000000+09:00`,
    record_date: recordDate,
    kind: "too_sick",
    by_proxy: false,
    skill_version: "regimen-folfox@1",
    answers: [],
    free_text: null,
  };
}

describe("toVisitEntry", () => {
  it("is the shape the server accepts (the fixture of POST /api/visit)", () => {
    const request = apiFixture("visit_with_entries").request as VisitRequest;
    const sent = request.entries?.[0] as VisitEntry;
    const device: DeviceEntry = {
      ...sent,
      pid: "P-DEMO0001",
      answers: sent.answers.map((answer) => ({
        question_key: answer.question_key,
        value: answer.value,
        temperature: answer.temperature ?? null,
        question_text: "copy of the question",
      })),
    };
    expect(toVisitEntry(device)).toEqual(sent);
  });

  it("does not change the entry it is given", () => {
    const device: DeviceEntry = {
      ...entry("a", "2026-11-01"),
      answers: [
        {
          question_key: "fever",
          value: "measured",
          temperature: 38.2,
          question_text: "copy",
        },
      ],
    };
    const before = structuredClone(device);
    toVisitEntry(device);
    expect(device).toEqual(before);
  });
});

describe("entriesInWindow", () => {
  it("keeps both ends and drops what is outside", () => {
    const sent = entriesInWindow(
      [
        entry("before", "2026-10-12"),
        entry("start", "2026-10-13"),
        entry("middle", "2026-11-01"),
        entry("end", "2026-11-09"),
        entry("after", "2026-11-10"),
      ],
      WINDOW,
    );
    expect(sent.map((e) => e.client_entry_id)).toEqual([
      "start",
      "middle",
      "end",
    ]);
  });

  it("nothing in the window: an empty list", () => {
    expect(entriesInWindow([entry("old", "2026-01-01")], WINDOW)).toEqual([]);
  });

  /** この修正の前に保存された記録。受付が断るので、1件で受診の全体が送れなくなる。 */
  describe("a record the server would refuse", () => {
    const ANSWER = {
      question_key: "diarrhea",
      value: "present",
      temperature: null,
      question_text: "copy",
    } as const;
    const DAY = "2026-11-01";

    function freeOnly(id: string, text: string): DeviceEntry {
      return { ...entry(id, DAY), kind: "free_text", free_text: text };
    }

    function mixed(id: string, text: string): DeviceEntry {
      return {
        ...entry(id, DAY),
        kind: "mixed",
        answers: [ANSWER],
        free_text: text,
      };
    }

    it("free text of only spaces is left out, and the others are still sent", () => {
      const sent = entriesInWindow(
        [freeOnly("x85", "\u0085"), entry("good", DAY)],
        WINDOW,
      );
      expect(sent.map((e) => e.client_entry_id)).toEqual(["good"]);
    });

    it("with answers: only the answers are sent, as kind answers", () => {
      const [sent] = entriesInWindow([mixed("a", "\u001c")], WINDOW);
      expect(sent).toMatchObject({
        client_entry_id: "a",
        kind: "answers",
        free_text: null,
      });
      expect(sent?.answers).toHaveLength(1);
    });

    it("cleans the text and keeps the kind when text is left", () => {
      const sent = entriesInWindow(
        [freeOnly("a", "\u0085だるい\ud83d"), mixed("b", "夜 熱\u001f")],
        WINDOW,
      );
      expect(sent.map((e) => [e.kind, e.free_text])).toEqual([
        ["free_text", "だるい"],
        ["mixed", "夜 熱"],
      ]);
    });

    it("does not change the entries it is given", () => {
      const device = [mixed("a", "\u001c")];
      const before = structuredClone(device);
      entriesInWindow(device, WINDOW);
      expect(device).toEqual(before);
    });
  });
});
