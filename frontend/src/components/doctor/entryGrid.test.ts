import { describe, expect, it } from "vitest";
import { doctorEntryStub, patientVisitStub } from "../../test/doctorStubs";
import { gridColumns, gridRows, visitDays } from "./entryGrid";

const level = (question_key: string, value: "none" | "present" | "hard") => ({
  question_key,
  value,
  temperature: null,
  question_label: null,
});

describe("gridColumns", () => {
  it("経過表の順（しびれ・下痢…）に並べ、体温は症状の後ろ", () => {
    const columns = gridColumns([
      doctorEntryStub({
        answers: [
          {
            question_key: "fever",
            value: "measured",
            temperature: 37.2,
            question_label: null,
          },
          level("diarrhea", "present"),
          level("numbness", "none"),
        ],
      }),
    ]);
    expect(columns).toEqual([
      { key: "numbness", label: "しびれ", kind: "level" },
      { key: "diarrhea", label: "下痢", kind: "level" },
      { key: "fever", label: "体温", kind: "temperature" },
    ]);
  });

  it("質問集の版で質問が違っても question_key で1列にまとめる（列がずれない）", () => {
    const columns = gridColumns([
      doctorEntryStub({ id: 2, answers: [level("hand_foot", "hard")] }),
      doctorEntryStub({
        id: 1,
        answers: [level("diarrhea", "none"), level("taste", "present")],
      }),
      doctorEntryStub({ id: 0, answers: [level("diarrhea", "hard")] }),
    ]);
    expect(columns.map((c) => c.key)).toEqual([
      "diarrhea",
      "hand_foot",
      "taste",
    ]);
    expect(columns[2]).toEqual({ key: "taste", label: "taste", kind: "level" });
  });

  it("知らない質問は最初に出てきた順で、既知の質問の後ろ", () => {
    const columns = gridColumns([
      doctorEntryStub({
        answers: [level("zeta", "none"), level("alpha", "none")],
      }),
      doctorEntryStub({ answers: [level("numbness", "none")] }),
    ]);
    expect(columns.map((c) => c.key)).toEqual(["numbness", "zeta", "alpha"]);
  });

  it("体温の答え（測った・測っていない）がある質問は体温の列", () => {
    const columns = gridColumns([
      doctorEntryStub({
        answers: [
          {
            question_key: "temp2",
            value: "not_measured",
            temperature: null,
            question_label: null,
          },
        ],
      }),
    ]);
    expect(columns).toEqual([
      { key: "temp2", label: "temp2", kind: "temperature" },
    ]);
  });

  it("知らない質問は記録の版の短い名前（question_label）、既知の質問は画面の名前（T95）", () => {
    const columns = gridColumns([
      doctorEntryStub({
        id: 2,
        answers: [
          { ...level("fatigue", "present"), question_label: "だるさ" },
          { ...level("hand_foot", "none"), question_label: "手足の皮膚" },
          level("bleeding", "none"),
        ],
      }),
      doctorEntryStub({
        id: 1,
        answers: [{ ...level("bleeding", "none"), question_label: "出血" }],
      }),
    ]);
    expect(columns).toEqual([
      { key: "hand_foot", label: "手のひら・足の裏", kind: "level" },
      { key: "fatigue", label: "だるさ", kind: "level" },
      { key: "bleeding", label: "出血", kind: "level" },
    ]);
  });

  it("回答が無ければ列も無い", () => {
    expect(gridColumns([doctorEntryStub({ kind: "too_sick" })])).toEqual([]);
  });
});

describe("visitDays", () => {
  it("1日1件（その日の最初の受付）を新しい順", () => {
    const days = visitDays([
      patientVisitStub({
        id: 3,
        visit_date: "2026-11-09",
        created_at: "2026-11-09T18:16:00+09:00",
      }),
      patientVisitStub({
        id: 2,
        visit_date: "2026-11-09",
        created_at: "2026-11-09T09:40:00+09:00",
      }),
      patientVisitStub({
        id: 1,
        visit_date: "2026-10-27",
        created_at: "2026-10-27T10:00:00+09:00",
      }),
    ]);
    expect(days).toEqual([
      { visit_date: "2026-11-09", received_at: "2026-11-09T09:40:00+09:00" },
      { visit_date: "2026-10-27", received_at: "2026-10-27T10:00:00+09:00" },
    ]);
  });
});

describe("gridRows", () => {
  const e = (id: number, recorded_at: string) =>
    doctorEntryStub({ id, recorded_at, record_date: recorded_at.slice(0, 10) });
  const v = (created_at: string) =>
    patientVisitStub({ visit_date: created_at.slice(0, 10), created_at });
  const shape = (rows: ReturnType<typeof gridRows>) =>
    rows.map((r) =>
      r.kind === "entry" ? r.entry.id : `受診 ${r.visit.visit_date}`,
    );

  it("受付の時刻の位置に受診日の行を入れる（後の記録は上、前の記録は下）", () => {
    const rows = gridRows(
      [
        e(3, "2026-11-09T20:00:00+09:00"),
        e(2, "2026-11-09T08:00:00+09:00"),
        e(1, "2026-11-05T20:00:00+09:00"),
      ],
      [v("2026-11-09T09:40:00+09:00")],
      false,
    );
    expect(shape(rows)).toEqual([3, "受診 2026-11-09", 2, 1]);
  });

  it("受付と同じ時刻の記録は受付の前（線の下）", () => {
    const rows = gridRows(
      [e(2, "2026-11-09T09:40:00+09:00")],
      [v("2026-11-09T09:40:00+09:00")],
      false,
    );
    expect(shape(rows)).toEqual(["受診 2026-11-09", 2]);
  });

  it("全ての記録より前の受診は下に足す（記録が全部出ている時）", () => {
    const rows = gridRows(
      [e(1, "2026-11-05T20:00:00+09:00")],
      [v("2026-10-27T10:00:00+09:00")],
      false,
    );
    expect(shape(rows)).toEqual([1, "受診 2026-10-27"]);
  });

  it("記録を直近だけ出している時は、出した記録より前の受診を出さない", () => {
    const rows = gridRows(
      [e(1, "2026-11-05T20:00:00+09:00")],
      [v("2026-11-09T09:40:00+09:00"), v("2026-10-27T10:00:00+09:00")],
      true,
    );
    expect(shape(rows)).toEqual(["受診 2026-11-09", 1]);
  });

  it("記録が無ければ受診日の行だけ", () => {
    const rows = gridRows([], [v("2026-11-09T09:40:00+09:00")], false);
    expect(shape(rows)).toEqual(["受診 2026-11-09"]);
  });

  it("記録は API の順によらず新しい順に並べる（引数は書き換えない）", () => {
    const entries = [
      e(1, "2026-11-05T20:00:00+09:00"),
      e(2, "2026-11-06T20:00:00+09:00"),
    ];
    const rows = gridRows(entries, [], false);
    expect(shape(rows)).toEqual([2, 1]);
    expect(entries.map((x) => x.id)).toEqual([1, 2]);
  });
});
