import { describe, expect, it } from "vitest";
import type { DeviceEntry, PatientVisitDay } from "../../api/types";
import { historyRows } from "./historyRows";

function entry(id: number, recordedAt: string): DeviceEntry {
  return {
    pid: "P-DEMO0001",
    client_entry_id: String(id),
    recorded_at: recordedAt,
    record_date: recordedAt.slice(0, 10),
    kind: "too_sick",
    by_proxy: false,
    skill_version: "regimen-folfox@1",
    answers: [],
    free_text: null,
  };
}

function visit(receivedAt: string): PatientVisitDay {
  return { visit_date: receivedAt.slice(0, 10), received_at: receivedAt };
}

/** 行を短い印に（e<id> は記録、v<日付> は受診日の区切り）。 */
function labels(rows: ReturnType<typeof historyRows>): string[] {
  return rows.map((row) =>
    row.kind === "entry"
      ? `e${row.entry.client_entry_id}`
      : `v${row.visit.visit_date}`,
  );
}

describe("historyRows (records and visit-day dividers, newest first)", () => {
  it("no visits: the records newest first, unchanged", () => {
    const rows = historyRows(
      [
        entry(1, "2026-11-01T08:00:00+09:00"),
        entry(2, "2026-11-02T08:00:00+09:00"),
      ],
      [],
    );
    expect(labels(rows)).toEqual(["e2", "e1"]);
  });

  it("the divider sits at the reception time: later records above, earlier below", () => {
    const rows = historyRows(
      [
        entry(1, "2026-11-08T21:00:00+09:00"),
        entry(2, "2026-11-09T08:10:00+09:00"),
        entry(3, "2026-11-09T13:47:00+09:00"),
        entry(4, "2026-11-10T20:00:00+09:00"),
      ],
      [visit("2026-11-09T09:40:00+09:00")],
    );
    expect(labels(rows)).toEqual(["e4", "e3", "v2026-11-09", "e2", "e1"]);
  });

  it("a record at the same time as the reception is before it (below the line)", () => {
    // db.undo_too_sick_entry と同じ（受付の created_at >= recorded_at なら受付が後）
    const rows = historyRows(
      [entry(7, "2026-11-09T10:00:00+09:00")],
      [visit("2026-11-09T10:00:00+09:00")],
    );
    expect(labels(rows)).toEqual(["v2026-11-09", "e7"]);
  });

  it("works with the server's microseconds (created_at has 6 fraction digits)", () => {
    const rows = historyRows(
      [
        entry(1, "2026-11-09T09:40:00.123455+09:00"),
        entry(2, "2026-11-09T09:40:00.900000+09:00"),
      ],
      [visit("2026-11-09T09:40:00.500000+09:00")],
    );
    expect(labels(rows)).toEqual(["e2", "v2026-11-09", "e1"]);
  });

  it("several visits, in any order from the API, are placed by time", () => {
    const rows = historyRows(
      [
        entry(1, "2026-10-20T20:00:00+09:00"),
        entry(2, "2026-10-30T20:00:00+09:00"),
        entry(3, "2026-11-10T20:00:00+09:00"),
      ],
      [visit("2026-10-27T09:00:00+09:00"), visit("2026-11-09T09:00:00+09:00")],
    );
    expect(labels(rows)).toEqual([
      "e3",
      "v2026-11-09",
      "e2",
      "v2026-10-27",
      "e1",
    ]);
  });

  it("a visit older than every record goes last; newer than every record goes first", () => {
    const rows = historyRows(
      [entry(1, "2026-11-01T08:00:00+09:00")],
      [visit("2026-10-27T09:00:00+09:00"), visit("2026-11-09T09:00:00+09:00")],
    );
    expect(labels(rows)).toEqual(["v2026-11-09", "e1", "v2026-10-27"]);
  });

  it("no records but visits: only the dividers", () => {
    expect(
      labels(historyRows([], [visit("2026-11-09T09:00:00+09:00")])),
    ).toEqual(["v2026-11-09"]);
  });

  it("does not change the arrays it was given", () => {
    const entries = [
      entry(1, "2026-11-01T08:00:00+09:00"),
      entry(2, "2026-11-02T08:00:00+09:00"),
    ];
    const visits = [
      visit("2026-10-27T09:00:00+09:00"),
      visit("2026-11-09T09:00:00+09:00"),
    ];
    const before = JSON.stringify([entries, visits]);
    historyRows(entries, visits);
    expect(JSON.stringify([entries, visits])).toBe(before);
  });
});
