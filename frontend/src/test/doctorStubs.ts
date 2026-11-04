/**
 * 医師画面のテスト用の、型どおりの応答の部品（本番コードからは import しない）。
 * 手で書いた偽の応答が guard（api/doctorGuards.ts）を通るように、必須の項目を全部埋める。
 */
import type {
  DoctorEntry,
  DoctorPatient,
  PatientVisit,
  UnprocessedItem,
  VisitHeader,
} from "../api/types";

/** 受付番号 A-023 の印刷待ち（ready）の受診の見出し。 */
export function visitHeaderStub(patch: Partial<VisitHeader> = {}): VisitHeader {
  return {
    id: 12,
    reception_no: "A-023",
    patient_id: "P-DEMO0001",
    visit_date: "2026-11-09",
    created_at: "2026-11-09T18:16:00+09:00",
    status: "ready",
    fallback: false,
    report_available: true,
    ...patch,
  };
}

export function doctorPatientStub(
  patch: Partial<DoctorPatient> = {},
): DoctorPatient {
  return {
    id: "P-DEMO0001",
    regimen: "FOLFOX",
    created_at: "2026-11-01T10:00:00+09:00",
    register_url: "http://localhost:5173/register?pid=P-DEMO0001",
    last_record_date: "2026-11-09",
    days_since_last_record: 0,
    record_stale: false,
    current_course_no: 3,
    current_day: 14,
    next_visit: "2026-11-23",
    ...patch,
  };
}

export function doctorEntryStub(patch: Partial<DoctorEntry> = {}): DoctorEntry {
  return {
    id: 1,
    recorded_at: "2026-11-05T20:00:00+09:00",
    record_date: "2026-11-05",
    course_no: 3,
    day: 10,
    kind: "answers",
    by_proxy: false,
    answers: [],
    has_free_text: false,
    ...patch,
  };
}

export function patientVisitStub(
  patch: Partial<PatientVisit> = {},
): PatientVisit {
  return {
    id: 12,
    reception_no: "A-023",
    visit_date: "2026-11-09",
    created_at: "2026-11-09T09:40:00+09:00",
    status: "ready",
    fallback: false,
    report_available: true,
    unprocessed_count: 0,
    ...patch,
  };
}

export function unprocessedItemStub(
  patch: Partial<UnprocessedItem> = {},
): UnprocessedItem {
  return {
    entry_id: 38,
    record_date: "2026-11-05",
    course_no: 3,
    day: 10,
    reason: "unknown_before_honorific",
    text: "磯鷲さんにもらった漢方",
    marks: [],
    doctor_mask: null,
    ...patch,
  };
}
