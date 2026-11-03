import { useCallback, useEffect, useState, type FormEvent } from "react";
import { createPatient, listPatients } from "../../api/doctor";
import {
  REGIMENS,
  type CreatePatientResponse,
  type DoctorPatient,
  type Regimen,
} from "../../api/types";
import { checked } from "../../api/validate";
import ErrorNote from "../../components/doctor/ErrorNote";
import {
  isCreatePatientResponse,
  isDoctorPatient,
} from "../../components/doctor/guards";
import { listOf } from "../../components/doctor/input";
import PatientTable from "../../components/doctor/PatientTable";
import RegisterQrPanel from "../../components/doctor/RegisterQrPanel";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import "../../components/doctor/doctor-ui.css";

interface Shown {
  id: string;
  url: string;
}

/** D1 患者一覧。仮名IDだけを扱う（氏名は扱わない）。登録用QRを描く。 */
export default function Patients() {
  const handleError = useDoctorApiError();
  const [patients, setPatients] = useState<DoctorPatient[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [regimen, setRegimen] = useState<Regimen>("FOLFOX");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);

  const load = useCallback(async () => {
    try {
      setPatients(
        listOf<DoctorPatient>(
          await listPatients(),
          "patients",
          isDoctorPatient,
        ),
      );
      setLoadError(null);
    } catch (err) {
      setLoadError(handleError(err));
    }
  }, [handleError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      const created = checked<CreatePatientResponse>(
        await createPatient(regimen),
        isCreatePatientResponse,
      );
      setCreatedId(created.id);
      setShown({ id: created.id, url: created.register_url });
      await load();
    } catch (err) {
      setCreateError(handleError(err));
    } finally {
      setCreating(false);
    }
  }

  function toggleQr(patient: DoctorPatient) {
    setShown((current) =>
      current?.id === patient.id
        ? null
        : { id: patient.id, url: patient.register_url },
    );
  }

  return (
    <section className="page">
      <h1>患者一覧</h1>
      <form className="d-inline-form" onSubmit={(e) => void handleCreate(e)}>
        <label className="d-field d-field--inline">
          <span>レジメン</span>
          <select
            value={regimen}
            onChange={(e) => setRegimen(e.target.value as Regimen)}
          >
            {REGIMENS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="d-primary" disabled={creating}>
          新規作成
        </button>
        <span className="d-muted">
          仮名IDは無作為に作られます。対応表は院内の紙で管理します。
        </span>
      </form>
      {createdId ? (
        <p role="status" className="d-ok">
          {createdId} を作りました。登録用QRを患者に読み取ってもらいます。
        </p>
      ) : null}
      {createError ? (
        <ErrorNote code={createError} prefix="作れませんでした" />
      ) : null}
      {shown ? (
        <RegisterQrPanel
          patientId={shown.id}
          url={shown.url}
          onClose={() => setShown(null)}
        />
      ) : null}
      {loadError ? (
        <ErrorNote code={loadError} prefix="一覧を取れません" />
      ) : null}
      {patients?.length === 0 ? (
        <p className="d-muted">登録された患者はいません</p>
      ) : null}
      {patients && patients.length > 0 ? (
        <PatientTable
          patients={patients}
          shownId={shown?.id ?? null}
          onToggleQr={toggleQr}
        />
      ) : null}
    </section>
  );
}
