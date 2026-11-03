import { describe, expect, it } from "vitest";
import type { Course } from "../../api/types";
import {
  courseToForm,
  delayDays,
  emptyCourseForm,
  formToCourse,
  nextCourseNo,
} from "./courseValues";

const c2: Course = {
  id: 7,
  patient_id: "P-DEMO0001",
  course_no: 2,
  infusion_date: "2026-10-13",
  planned_date: "2026-10-11",
  next_visit: null,
  note: null,
};

describe("nextCourseNo", () => {
  it("登録済みの最大の course_no + 1", () => {
    expect(nextCourseNo([c2, { ...c2, id: 6, course_no: 1 }])).toBe(3);
  });

  it("未登録なら 1", () => {
    expect(nextCourseNo([])).toBe(1);
  });
});

describe("emptyCourseForm / courseToForm", () => {
  it("新規は course_no だけ入れる", () => {
    expect(emptyCourseForm(3)).toEqual({
      id: null,
      course_no: "3",
      infusion_date: "",
      planned_date: "",
      next_visit: "",
      note: "",
    });
  });

  it("既存のコースは null を空文字にして写す", () => {
    expect(courseToForm(c2)).toEqual({
      id: 7,
      course_no: "2",
      infusion_date: "2026-10-13",
      planned_date: "2026-10-11",
      next_visit: "",
      note: "",
    });
  });
});

describe("formToCourse", () => {
  it("空欄は null、メモは前後の空白を落とす", () => {
    const result = formToCourse(
      {
        id: null,
        course_no: "3",
        infusion_date: "2026-10-27",
        planned_date: "",
        next_visit: "2026-11-09",
        note: "  発熱で1日延期  ",
      },
      "P-DEMO0001",
    );
    expect(result).toEqual({
      ok: true,
      course: {
        patient_id: "P-DEMO0001",
        course_no: 3,
        infusion_date: "2026-10-27",
        planned_date: null,
        next_visit: "2026-11-09",
        note: "発熱で1日延期",
      },
    });
  });

  it("修正では id を付ける", () => {
    const result = formToCourse(courseToForm(c2), "P-DEMO0001");
    expect(result.ok && result.course.id).toBe(7);
  });

  it.each([
    [{ course_no: "0" }, "invalid_course_no"],
    [{ course_no: "1.5" }, "invalid_course_no"],
    [{ course_no: "" }, "invalid_course_no"],
    [{ course_no: "9007199254740992" }, "invalid_course_no"],
    [{ course_no: "9007199254740993" }, "invalid_course_no"],
    [{ infusion_date: "" }, "missing_infusion_date"],
    [{ infusion_date: "2026-13-01" }, "invalid_date"],
    [{ planned_date: "2026/10/11" }, "invalid_date"],
    [{ next_visit: "2026-02-30" }, "invalid_date"],
    [{ note: "あ".repeat(201) }, "note_too_long"],
    [{ note: "\u{1F600}".repeat(201) }, "note_too_long"],
  ])("%o は %s", (patch, code) => {
    const form = { ...courseToForm(c2), ...patch };
    expect(formToCourse(form, "P-DEMO0001")).toEqual({
      ok: false,
      error: code,
    });
  });

  it("course_no は安全な整数の上限（2^53 - 1）まで通す（丸めて別の番号を送らない）", () => {
    const form = { ...courseToForm(c2), course_no: "9007199254740991" };
    const result = formToCourse(form, "P-DEMO0001");
    expect(result.ok && result.course.course_no).toBe(Number.MAX_SAFE_INTEGER);
  });

  it.each([
    ["200字の日本語", "あ".repeat(200)],
    ["200字の絵文字（UTF-16 では400単位）", "\u{1F600}".repeat(200)],
  ])("メモは文字数（code point）で200字まで: %s は通す", (_l, note) => {
    const form = { ...courseToForm(c2), note };
    const result = formToCourse(form, "P-DEMO0001");
    expect(result.ok && result.course.note).toBe(note);
  });

  it("引数のフォームを書き換えない", () => {
    const form = Object.freeze(courseToForm(c2));
    expect(() => formToCourse(form, "P-DEMO0001")).not.toThrow();
  });
});

describe("delayDays", () => {
  it("実投与日 − 予定日 の日数", () => {
    expect(delayDays(c2)).toBe(2);
  });

  it("予定日が無いか同じ日なら null", () => {
    expect(delayDays({ ...c2, planned_date: null })).toBeNull();
    expect(delayDays({ ...c2, planned_date: "2026-10-13" })).toBeNull();
  });

  it("予定より早い日は負の数", () => {
    expect(delayDays({ ...c2, planned_date: "2026-10-14" })).toBe(-1);
  });
});
