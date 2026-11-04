import type { Course } from "../../api/types";
import { delayDays } from "./courseValues";
import { formatDay } from "./dayLabel";

const NONE = "—";

function dayOrNone(value: string | null | undefined): string {
  return value ? formatDay(value) : NONE;
}

function delayText(course: Course): string {
  const days = delayDays(course);
  if (days === null) {
    return NONE;
  }
  return days > 0 ? `予定より${days}日延期` : `予定より${-days}日早い`;
}

interface CourseTableProps {
  courses: readonly Course[];
  editingNo: number | null;
  onEdit: (course: Course) => void;
}

/**
 * D2 のコース一覧（course_no 順で渡す）。延期は日数だけを出し、理由は書かない。
 * 日付は「11月9日（月）」（入力欄は type=date のまま）。
 */
export default function CourseTable({
  courses,
  editingNo,
  onEdit,
}: CourseTableProps) {
  return (
    <table className="d-table d-table--middle">
      <thead>
        <tr>
          <th scope="col">コース</th>
          <th scope="col">実投与日（Day1）</th>
          <th scope="col">予定日</th>
          <th scope="col">延期</th>
          <th scope="col">次回受診</th>
          <th scope="col">メモ</th>
          <th scope="col">操作</th>
        </tr>
      </thead>
      <tbody>
        {courses.map((course) => (
          <tr
            key={course.course_no}
            className={course.course_no === editingNo ? "d-row-editing" : ""}
          >
            <td>第{course.course_no}コース</td>
            <td className="d-nowrap">{formatDay(course.infusion_date)}</td>
            <td className="d-nowrap">{dayOrNone(course.planned_date)}</td>
            <td>{delayText(course)}</td>
            <td className="d-nowrap">{dayOrNone(course.next_visit)}</td>
            <td>{course.note ?? ""}</td>
            <td>
              <button type="button" onClick={() => onEdit(course)}>
                修正
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
