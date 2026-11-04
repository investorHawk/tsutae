import { Link, useParams } from "react-router-dom";
import OpenVisits from "../../components/doctor/OpenVisits";
import PatientCourseEditor from "../../components/doctor/PatientCourseEditor";
import PatientEntries from "../../components/doctor/PatientEntries";
import PatientSummary from "../../components/doctor/PatientSummary";
import PatientVisits from "../../components/doctor/PatientVisits";
import { usePatientCourses } from "../../components/doctor/usePatientCourses";
import { usePatientRecords } from "../../components/doctor/usePatientRecords";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import "../../components/doctor/doctor-ui.css";
import "../../components/doctor/board.css";

/**
 * D2 患者の画面。上から: 見出しと要約の行（レジメン・今のコースと Day・最後の記録日・
 * 次回受診）、「印刷待ちの受診」（あれば）、「コース」（追加の欄はたたむ）、「記録」（経過表と
 * 受診日の線）、「受診」（履歴。印刷済み・期限切れも）。
 * 患者ごとに描き直す（別の患者へ移ったら、フォーム・知らせ・送信中・記録を前の患者から
 * 引き継がない）。
 */
export default function PatientDetail() {
  const { pid = "" } = useParams();
  return <PatientView key={pid} pid={pid} />;
}

function PatientView({ pid }: { pid: string }) {
  const handleError = useDoctorApiError();
  const { patient, reloadPatient, courses, loadError, reload } =
    usePatientCourses(pid, handleError);
  const records = usePatientRecords(pid, handleError);
  return (
    <section className="page">
      <div className="d-page-head">
        <h1>
          患者 <code>{pid}</code>
        </h1>
        <Link className="d-sublink d-head-action" to="/doctor/patients">
          患者一覧へ戻る
        </Link>
      </div>
      <PatientSummary patient={patient} />
      <OpenVisits visits={records.visits} />
      <PatientCourseEditor
        pid={pid}
        courses={courses}
        loadError={loadError}
        reload={reload}
        onSaved={reloadPatient}
      />
      <PatientEntries entries={records.entries} visits={records.visits} />
      <PatientVisits visits={records.visits} />
    </section>
  );
}
