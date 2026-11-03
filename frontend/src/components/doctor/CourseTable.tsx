import type { Course } from "../../api/types";
import { delayDays } from "./courseValues";

function delayText(course: Course): string {
  const days = delayDays(course);
  if (days === null) {
    return "—";
  }
  return days > 0 ? `予定より${days}日延期` : `予定より${-days}日早い`;
}

interface CourseTableProps {
  courses: readonly Course[];
  editingNo: number | null;
  onEdit: (course: Course) => void;
}

/** D2 のコース一覧（course_no 順で渡す）。延期は日数だけを出し、理由は書かない。 */
export default function CourseTable({
  courses,
  editingNo,
  onEdit,
}: CourseTableProps) {
  return (
    <table className="d-table">
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
            <td>{course.infusion_date}</td>
            <td>{course.planned_date ?? "—"}</td>
            <td>{delayText(course)}</td>
            <td>{course.next_visit ?? "—"}</td>
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
