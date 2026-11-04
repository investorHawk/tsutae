/** 「第3コース Day14」。コースが無ければ null、Day が無ければ「第3コース」だけ。 */
export function courseDayLabel(
  courseNo: number | null,
  day: number | null,
): string | null {
  if (courseNo === null) {
    return null;
  }
  return day === null ? `第${courseNo}コース` : `第${courseNo}コース Day${day}`;
}
