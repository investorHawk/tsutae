/**
 * 契約テスト（日時・日付・必須項目の境界）: 実際の FastAPI の成功の本文を、日時の形
 * （+09:00 付き ISO 8601）・暦に実在する日・型どおりの必須／nullable の境界で壊すと、
 * guard が拒むこと（契約外の 200 を invalid_response にする。§9 W2b の決定）。
 */
import { describe, expect, it } from "vitest";
import { fixtureBody } from "../test/apiFixtures";
import {
  isCoursesResponse,
  isCreateSkillChangeResponse,
  isPatientEntriesSummaryResponse,
  isPatientVisitsResponse,
  isPatientsResponse,
  isPipelineEventsResponse,
  isSkillChangesResponse,
  isUnprocessedResponse,
  isVisitsResponse,
} from "./doctorGuards";
import { isPatientEntriesResponse } from "./patientGuards";
import { type Item, isRecord } from "./validate";

type Guard = (body: Item) => boolean;

const GUARDS: Readonly<Record<string, Guard>> = {
  doctor_visits: isVisitsResponse,
  doctor_patients: isPatientsResponse,
  doctor_patient_visits: isPatientVisitsResponse,
  doctor_patient_entries: isPatientEntriesSummaryResponse,
  doctor_courses: isCoursesResponse,
  doctor_unprocessed: isUnprocessedResponse,
  doctor_pipeline_events: isPipelineEventsResponse,
  doctor_skill_changes: isSkillChangesResponse,
  doctor_skill_change_create: isCreateSkillChangeResponse,
  patient_entries: isPatientEntriesResponse,
};

function passes(name: string, body: unknown): boolean {
  const guard = GUARDS[name];
  if (!guard) {
    throw new Error(`guard が無い: ${name}`);
  }
  return isRecord(body) && guard(body);
}

// 壊す操作を短く書くため、ここだけ any を使う（本文は fixtureBody の深い写し）
type Mutate = (body: any) => void;

const NO_OFFSET = "2026-11-09T10:00:00";
const UTC = "2026-11-09T01:00:00Z";
const NOT_A_DAY = "2026-02-30T10:00:00+09:00";
const FREE_TEXT = "きのう";

/** 日時の項目（fixture, 説明, 値を差し替える操作）。 */
function dateTimeCases(
  name: string,
  field: string,
  set: (b: any, value: unknown) => void,
): Array<[string, string, Mutate]> {
  return [
    [name, `${field} に時差が無い`, (b) => set(b, NO_OFFSET)],
    [name, `${field} が UTC（Z）`, (b) => set(b, UTC)],
    [name, `${field} が存在しない日`, (b) => set(b, NOT_A_DAY)],
    [name, `${field} が任意の文字列`, (b) => set(b, FREE_TEXT)],
  ];
}

/** 日付の項目（YYYY-MM-DD・暦に実在する日）。 */
function dateCases(
  name: string,
  field: string,
  set: (b: any, value: unknown) => void,
): Array<[string, string, Mutate]> {
  return [
    [name, `${field} が存在しない日`, (b) => set(b, "2026-02-30")],
    [name, `${field} が13月`, (b) => set(b, "2026-13-01")],
    [name, `${field} が日時`, (b) => set(b, "2026-11-05T00:00:00+09:00")],
  ];
}

const BROKEN: Array<[string, string, Mutate]> = [
  ...dateTimeCases("doctor_visits", "created_at", (b, v) => {
    b.visits[0].created_at = v;
  }),
  ...dateTimeCases("doctor_visits", "expires_at", (b, v) => {
    b.visits[0].expires_at = v;
  }),
  ...dateTimeCases("doctor_patients", "created_at", (b, v) => {
    b.patients[0].created_at = v;
  }),
  ...dateTimeCases("doctor_pipeline_events", "ts", (b, v) => {
    b.events[0].ts = v;
  }),
  ...dateTimeCases("doctor_skill_changes", "created_at", (b, v) => {
    b.skill_changes[0].created_at = v;
  }),
  ...dateTimeCases("doctor_skill_changes", "decided_at", (b, v) => {
    b.skill_changes[0].decided_at = v;
  }),
  ...dateTimeCases("patient_entries", "recorded_at", (b, v) => {
    b.entries[0].recorded_at = v;
  }),
  ...dateCases("patient_entries", "record_date", (b, v) => {
    b.entries[0].record_date = v;
  }),
  ...dateCases("doctor_unprocessed", "record_date", (b, v) => {
    b.entries[0].record_date = v;
  }),
  ...dateCases("doctor_patients", "last_record_date", (b, v) => {
    b.patients[0].last_record_date = v;
  }),
  ...dateCases("doctor_patients", "next_visit", (b, v) => {
    b.patients[1].next_visit = v;
  }),
  ...dateCases("doctor_patient_visits", "visit_date", (b, v) => {
    b.visits[0].visit_date = v;
  }),
  ...dateTimeCases("doctor_patient_visits", "created_at", (b, v) => {
    b.visits[0].created_at = v;
  }),
  ...dateTimeCases("doctor_patient_entries", "recorded_at", (b, v) => {
    b.entries[0].recorded_at = v;
  }),
  ...dateCases("doctor_patient_entries", "record_date", (b, v) => {
    b.entries[0].record_date = v;
  }),
  ...dateCases("doctor_courses", "infusion_date", (b, v) => {
    b.courses[0].infusion_date = v;
  }),
  ...dateCases("doctor_courses", "planned_date", (b, v) => {
    b.courses[0].planned_date = v;
  }),
  // SkillChange: requested_text は必須の文字列、nullable の項目も省略は不正
  [
    "doctor_skill_changes",
    "requested_text が null",
    (b) => (b.skill_changes[0].requested_text = null),
  ],
  [
    "doctor_skill_changes",
    "requested_text が無い",
    (b) => delete b.skill_changes[0].requested_text,
  ],
  ...["diff", "new_version", "error_code", "decided_at"].map(
    (key): [string, string, Mutate] => [
      "doctor_skill_changes",
      `${key} が無い（null と省略は違う）`,
      (b) => delete b.skill_changes[0][key],
    ],
  ),
  [
    "doctor_skill_change_create",
    "diff が無い（null と省略は違う）",
    (b) => delete b.diff,
  ],
  // D5: nullable の項目も省略は不正
  ...["hook_name", "agent_type", "tool_name", "decision", "duration_ms"].map(
    (key): [string, string, Mutate] => [
      "doctor_pipeline_events",
      `${key} が無い（null と省略は違う）`,
      (b) => delete b.events[0][key],
    ],
  ),
];

describe("日時・日付・必須項目の境界を壊した fixture は guard に拒まれる", () => {
  it.each(BROKEN)("%s: %s", (name, _label, mutate) => {
    const body = fixtureBody(name);
    expect(passes(name, body)).toBe(true);
    mutate(body);
    expect(passes(name, body)).toBe(false);
  });
});

describe("guard は本番の形の日時を受け入れる（fixture は時計を止めているので小数秒が無い）", () => {
  it.each(["2026-11-09T10:00:00.4+09:00", "2026-11-09T10:00:00.123456+09:00"])(
    "ts・created_at が %s でも通る",
    (value) => {
      const events: any = fixtureBody("doctor_pipeline_events");
      events.events[0].ts = value;
      expect(passes("doctor_pipeline_events", events)).toBe(true);
      const changes: any = fixtureBody("doctor_skill_changes");
      changes.skill_changes[0].created_at = value;
      changes.skill_changes[0].decided_at = value;
      expect(passes("doctor_skill_changes", changes)).toBe(true);
    },
  );

  it("decided_at・diff・error_code は null でよい（pending の行）", () => {
    const changes: any = fixtureBody("doctor_skill_changes");
    Object.assign(changes.skill_changes[0], {
      decided_at: null,
      diff: null,
      new_version: null,
      error_code: null,
    });
    expect(passes("doctor_skill_changes", changes)).toBe(true);
  });
});
