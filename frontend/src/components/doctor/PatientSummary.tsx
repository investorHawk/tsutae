import type { DoctorPatient } from "../../api/types";
import { courseDayLabel } from "./courseDayLabel";
import { formatDay } from "./dayLabel";
import RecordGapFlag from "./RecordGapFlag";
import "./board.css";

const NONE = "—";

/**
 * D2 の見出しの下の要約の行: レジメン・今のコース（第3コース Day14）・最後の記録日（途切れの
 * 印）・次回受診。値は患者一覧の API の行（今日で計算済み）。行が無ければ全て「—」。
 */
export default function PatientSummary({
  patient,
}: {
  patient: DoctorPatient | null;
}) {
  const course = patient
    ? courseDayLabel(patient.current_course_no, patient.current_day)
    : null;
  return (
    <dl className="d-patient-summary" aria-label="患者の要約">
      <div>
        <dt>レジメン</dt>
        <dd>{patient?.regimen ?? NONE}</dd>
      </div>
      <div>
        <dt>今のコース</dt>
        <dd>{course ?? NONE}</dd>
      </div>
      <div>
        <dt>最後の記録</dt>
        <dd className="d-cell-flags">
          <span>
            {patient?.last_record_date
              ? formatDay(patient.last_record_date)
              : NONE}
          </span>
          {patient ? <RecordGapFlag gap={patient} /> : null}
        </dd>
      </div>
      <div>
        <dt>次回受診</dt>
        <dd>{patient?.next_visit ? formatDay(patient.next_visit) : NONE}</dd>
      </div>
    </dl>
  );
}
