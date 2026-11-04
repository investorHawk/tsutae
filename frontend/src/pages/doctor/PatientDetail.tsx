import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { saveCourse } from "../../api/doctor";
import CourseForm from "../../components/doctor/CourseForm";
import CourseTable from "../../components/doctor/CourseTable";
import {
  courseToForm,
  emptyCourseForm,
  formToCourse,
  nextCourseNo,
  type CourseFormValues,
} from "../../components/doctor/courseValues";
import ErrorNote from "../../components/doctor/ErrorNote";
import PatientEntries from "../../components/doctor/PatientEntries";
import PatientVisits from "../../components/doctor/PatientVisits";
import {
  usePatientCourses,
  type PatientCourses,
} from "../../components/doctor/usePatientCourses";
import { usePatientRecords } from "../../components/doctor/usePatientRecords";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import "../../components/doctor/doctor-ui.css";

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

/**
 * D2 患者の画面。「コース」（実投与日・予定日・次回受診予定日の登録・修正）、「記録」
 * （直近の記録）、「受診」（受診の履歴とレポート）の節（D4-1）。
 * 患者ごとに描き直す（別の患者へ移ったら、フォーム・知らせ・送信中・記録を前の患者から
 * 引き継がない）。
 */
export default function PatientDetail() {
  const { pid = "" } = useParams();
  return <PatientView key={pid} pid={pid} />;
}

function PatientView({ pid }: { pid: string }) {
  const handleError = useDoctorApiError();
  const { regimen, ...courseState } = usePatientCourses(pid, handleError);
  const records = usePatientRecords(pid, handleError);
  return (
    <section className="page">
      <h1>
        患者 <code>{pid}</code>
      </h1>
      <p className="d-patient-head">
        <span className="d-muted">レジメン </span>
        <span>{regimen ?? "—"}</span>
        <Link className="d-sublink" to="/doctor/patients">
          患者一覧へ戻る
        </Link>
      </p>
      <PatientCourseEditor pid={pid} {...courseState} />
      <PatientEntries entries={records.entries} />
      <PatientVisits visits={records.visits} />
    </section>
  );
}

function PatientCourseEditor({
  pid,
  courses,
  loadError,
  reload,
}: { pid: string } & Omit<PatientCourses, "regimen">) {
  const handleError = useDoctorApiError();
  const [form, setForm] = useState<CourseFormValues>(emptyCourseForm(1));
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    void reload().then((list) => {
      if (list) {
        setForm(emptyCourseForm(nextCourseNo(list)));
      }
    });
  }, [reload]);

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
    } catch (err) {
      setNotice({ kind: "failed", code: handleError(err) });
    } finally {
      setBusy(false);
    }
  }

  function editCourse(values: CourseFormValues) {
    setNotice(null);
    setForm(values);
  }

  return (
    <section className="d-section" aria-labelledby="d-sec-courses">
      <h2 id="d-sec-courses">コース</h2>
      {loadError ? (
        <ErrorNote code={loadError} prefix="コースを取れません" />
      ) : null}
      {courses?.length === 0 ? (
        <p className="d-muted">まだコースが登録されていません</p>
      ) : null}
      {courses && courses.length > 0 ? (
        <CourseTable
          courses={courses}
          editingNo={form.id !== null ? Number(form.course_no) : null}
          onEdit={(course) => editCourse(courseToForm(course))}
        />
      ) : null}
      <CourseForm
        values={form}
        busy={busy}
        onChange={setForm}
        onSubmit={() => void handleSubmit()}
        onCancelEdit={() =>
          editCourse(emptyCourseForm(nextCourseNo(courses ?? [])))
        }
      />
      <NoticeView notice={notice} />
    </section>
  );
}
