/**
 * D2 のコース登録フォーム。入力欄は文字列で持ち、送る前に Course へ直して検査する。
 * 実投与日の矛盾（逆転・重複）はサーバーが 400 {"error": code} で返す。
 */
import type { Course, IsoDate } from "../../api/types";

export interface CourseFormValues {
  /** 修正のときだけ既存のコースの id */
  id: number | null;
  course_no: string;
  infusion_date: string;
  planned_date: string;
  next_visit: string;
  note: string;
}

export type CourseFormError =
  | "invalid_course_no"
  | "missing_infusion_date"
  | "invalid_date"
  | "note_too_long";

export type CourseFormResult =
  | { ok: true; course: Course }
  | { ok: false; error: CourseFormError };

/** Course.note の上限（schemas.py の max_length=200。Python の len と同じく code point で数える） */
export const NOTE_MAX_LENGTH = 200;

function codePointLength(text: string): number {
  return [...text].length;
}

const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const DAY_MS = 24 * 60 * 60 * 1000;

export function nextCourseNo(courses: readonly Course[]): number {
  return courses.reduce((max, c) => Math.max(max, c.course_no), 0) + 1;
}

export function emptyCourseForm(courseNo: number): CourseFormValues {
  return {
    id: null,
    course_no: String(courseNo),
    infusion_date: "",
    planned_date: "",
    next_visit: "",
    note: "",
  };
}

export function courseToForm(course: Course): CourseFormValues {
  return {
    id: course.id ?? null,
    course_no: String(course.course_no),
    infusion_date: course.infusion_date,
    planned_date: course.planned_date ?? "",
    next_visit: course.next_visit ?? "",
    note: course.note ?? "",
  };
}

/** "YYYY-MM-DD" を UTC 0 時の ms にする。暦に無い日（2/30 等）は null。 */
function dateValue(value: string): number | null {
  const match = DATE_PATTERN.exec(value);
  if (!match) {
    return null;
  }
  const [year, month, day] = [match[1], match[2], match[3]].map(Number);
  const ms = Date.UTC(year, month - 1, day);
  const back = new Date(ms);
  const sameDay =
    back.getUTCFullYear() === year &&
    back.getUTCMonth() === month - 1 &&
    back.getUTCDate() === day;
  return sameDay ? ms : null;
}

function optionalDate(value: string): IsoDate | null | "invalid" {
  const trimmed = value.trim();
  if (trimmed === "") {
    return null;
  }
  return dateValue(trimmed) === null ? "invalid" : trimmed;
}

export function formToCourse(
  form: CourseFormValues,
  patientId: string,
): CourseFormResult {
  const courseNoText = form.course_no.trim();
  const courseNo = Number(courseNoText);
  // 2^53 以上は Number で丸まり、別のコース番号を送ってしまう
  if (
    !/^\d+$/.test(courseNoText) ||
    !Number.isSafeInteger(courseNo) ||
    courseNo < 1
  ) {
    return { ok: false, error: "invalid_course_no" };
  }
  const infusion = form.infusion_date.trim();
  if (infusion === "") {
    return { ok: false, error: "missing_infusion_date" };
  }
  const planned = optionalDate(form.planned_date);
  const nextVisit = optionalDate(form.next_visit);
  if (
    dateValue(infusion) === null ||
    planned === "invalid" ||
    nextVisit === "invalid"
  ) {
    return { ok: false, error: "invalid_date" };
  }
  const note = form.note.trim();
  if (codePointLength(note) > NOTE_MAX_LENGTH) {
    return { ok: false, error: "note_too_long" };
  }
  const course: Course = {
    patient_id: patientId,
    course_no: courseNo,
    infusion_date: infusion,
    planned_date: planned,
    next_visit: nextVisit,
    note: note === "" ? null : note,
  };
  return {
    ok: true,
    course: form.id === null ? course : { ...course, id: form.id },
  };
}

/** 実投与日 − 予定日（日）。予定日が無い・同じ日なら null。 */
export function delayDays(course: Course): number | null {
  if (!course.planned_date) {
    return null;
  }
  const planned = dateValue(course.planned_date);
  const infusion = dateValue(course.infusion_date);
  if (planned === null || infusion === null || planned === infusion) {
    return null;
  }
  return Math.round((infusion - planned) / DAY_MS);
}
