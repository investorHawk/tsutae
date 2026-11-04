import { Link } from "react-router-dom";
import type { DoctorPatient } from "../../api/types";
import { courseDayLabel } from "./courseDayLabel";
import { formatDay } from "./dayLabel";
import RecordGapFlag from "./RecordGapFlag";

interface PatientTableProps {
  patients: readonly DoctorPatient[];
  /** QR を開いている患者の仮名ID */
  shownId: string | null;
  onToggleQr: (patient: DoctorPatient) => void;
}

const NONE = "—";

/**
 * D1 の一覧。仮名ID・レジメン・最後の記録日（途切れの印）・今のコース（と Day）・次回受診・
 * 作成日時・登録用QR（氏名の欄は無い）。値が無ければ「—」。日付は「11月9日（月）」。
 */
export default function PatientTable({
  patients,
  shownId,
  onToggleQr,
}: PatientTableProps) {
  return (
    <table className="d-table d-table--middle d-patients">
      <thead>
        <tr>
          <th scope="col">仮名ID</th>
          <th scope="col">レジメン</th>
          <th scope="col">最後の記録日</th>
          <th scope="col">今のコース</th>
          <th scope="col">次回受診</th>
          <th scope="col">作成</th>
          <th scope="col">登録用QR</th>
        </tr>
      </thead>
      <tbody>
        {patients.map((patient) => (
          <tr key={patient.id}>
            <td>
              <Link to={`/doctor/patients/${encodeURIComponent(patient.id)}`}>
                {patient.id}
              </Link>
            </td>
            <td>{patient.regimen}</td>
            <td>
              <span className="d-cell-flags">
                <span className="d-nowrap">
                  {patient.last_record_date !== null
                    ? formatDay(patient.last_record_date)
                    : NONE}
                </span>
                <RecordGapFlag gap={patient} />
              </span>
            </td>
            <td className="d-nowrap">
              {courseDayLabel(patient.current_course_no, patient.current_day) ??
                NONE}
            </td>
            <td className="d-nowrap">
              {patient.next_visit !== null
                ? formatDay(patient.next_visit)
                : NONE}
            </td>
            <td className="d-nowrap">{formatDay(patient.created_at)}</td>
            <td>
              <button
                type="button"
                aria-expanded={shownId === patient.id}
                onClick={() => onToggleQr(patient)}
              >
                登録用QR
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
