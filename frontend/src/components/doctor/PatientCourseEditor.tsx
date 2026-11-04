import { useEffect, useState } from "react";
import { saveCourse } from "../../api/doctor";
import CourseForm from "./CourseForm";
import CourseTable from "./CourseTable";
import {
  courseToForm,
  emptyCourseForm,
  formToCourse,
  nextCourseNo,
  type CourseFormValues,
} from "./courseValues";
import ErrorNote from "./ErrorNote";
import type { PatientCourses } from "./usePatientCourses";
import { useDoctorApiError } from "./useDoctorApiError";
import "./board.css";

type Notice =
  | { kind: "saved"; courseNo: number }
  | { kind: "invalid"; code: string }
  | { kind: "failed"; code: string };

function NoticeView({ notice }: { notice: Notice | null }) {
  if (notice?.kind === "saved") {
    return (
      <p role="status" className="d-ok">
        第{notice.courseNo}コースを保存しました
      </p>
    );
  }
  if (notice?.kind === "invalid") {
    return <ErrorNote code={notice.code} />;
  }
  if (notice?.kind === "failed") {
    return <ErrorNote code={notice.code} prefix="保存できませんでした" />;
  }
  return null;
}

type Props = { pid: string; onSaved: () => void } & Omit<
  PatientCourses,
  "regimen" | "patient" | "reloadPatient"
>;

/**
 * D2 の「コース」の節。入力の欄は普段は閉じ、「＋ コースを追加」か行の「修正」で開く。
 * 保存できたら閉じる（失敗した時は入力を残して開いたまま）。「やめる」で閉じると入力は
 * 捨てる（次に開く時は次のコース番号の空の欄から）。
 */
export default function PatientCourseEditor({
  pid,
  courses,
  loadError,
  reload,
  onSaved,
}: Props) {
  const handleError = useDoctorApiError();
  const [form, setForm] = useState<CourseFormValues>(emptyCourseForm(1));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    void reload();
  }, [reload]);

  function blankForm(): CourseFormValues {
    return emptyCourseForm(nextCourseNo(courses ?? []));
  }

  function openWith(values: CourseFormValues) {
    setNotice(null);
    setForm(values);
    setOpen(true);
  }

  function close() {
    setOpen(false);
    setForm(blankForm());
  }

  async function handleSubmit() {
    const result = formToCourse(form, pid);
    if (!result.ok) {
      setNotice({ kind: "invalid", code: result.error });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const saved = await saveCourse(result.course);
      setNotice({
        kind: "saved",
        courseNo:
          typeof saved?.course_no === "number"
            ? saved.course_no
            : result.course.course_no,
      });
      const list = await reload();
      setForm(emptyCourseForm(nextCourseNo(list ?? courses ?? [])));
      setOpen(false);
      onSaved();
    } catch (err) {
      setNotice({ kind: "failed", code: handleError(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="d-section" aria-labelledby="d-sec-courses">
      <div className="d-page-head">
        <h2 id="d-sec-courses">コース</h2>
        {!open ? (
          <button
            type="button"
            className="d-head-action"
            onClick={() => openWith(blankForm())}
          >
            ＋ コースを追加
          </button>
        ) : null}
      </div>
      {loadError ? (
        <ErrorNote code={loadError} prefix="コースを取れません" />
      ) : null}
      {courses?.length === 0 ? (
        <p className="d-muted">まだコースが登録されていません</p>
      ) : null}
      {courses && courses.length > 0 ? (
        <CourseTable
          courses={courses}
          editingNo={open && form.id !== null ? Number(form.course_no) : null}
          onEdit={(course) => openWith(courseToForm(course))}
        />
      ) : null}
      {open ? (
        <CourseForm
          values={form}
          busy={busy}
          onChange={setForm}
          onSubmit={() => void handleSubmit()}
          onCancel={close}
        />
      ) : null}
      <NoticeView notice={notice} />
    </section>
  );
}
