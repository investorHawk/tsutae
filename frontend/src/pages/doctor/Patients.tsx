import { useCallback, useEffect, useState } from "react";
import { createPatient, listPatients } from "../../api/doctor";
import type {
  CreatePatientResponse,
  DoctorPatient,
  Regimen,
} from "../../api/types";
import { checked } from "../../api/validate";
import ErrorNote from "../../components/doctor/ErrorNote";
import {
  isCreatePatientResponse,
  isDoctorPatient,
} from "../../components/doctor/guards";
import { listOf } from "../../components/doctor/input";
import PatientCreateForm from "../../components/doctor/PatientCreateForm";
import PatientTable from "../../components/doctor/PatientTable";
import RegisterQrPanel from "../../components/doctor/RegisterQrPanel";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import "../../components/doctor/doctor-ui.css";
import "../../components/doctor/board.css";

interface Shown {
  id: string;
  url: string;
}

/**
 * D1 患者一覧。仮名IDだけを扱う（氏名は扱わない）。登録用QRを描く。
 * 一覧には最後の記録日（途切れの印）・今のコースと Day・次回受診も出す（API が今日で計算する）。
 * 一覧をいちばん上に置き、追加の欄は見出しの右の「＋ 患者を追加」で開く。追加したら欄を
 * 閉じ、その患者の登録用QRを出す（QR の出方は前と同じ）。
 */
export default function Patients() {
  const handleError = useDoctorApiError();
  const [patients, setPatients] = useState<DoctorPatient[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
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

  async function handleCreate(regimen: Regimen) {
    setCreating(true);
    setCreateError(null);
    try {
      const created = checked<CreatePatientResponse>(
        await createPatient(regimen),
        isCreatePatientResponse,
      );
      setCreatedId(created.id);
      setShown({ id: created.id, url: created.register_url });
      setFormOpen(false);
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
      <div className="d-page-head">
        <h1>患者一覧</h1>
        <button
          type="button"
          className="d-head-action"
          aria-expanded={formOpen}
          aria-controls={formOpen ? "d-patient-add-form" : undefined}
          onClick={() => {
            setCreateError(null);
            setFormOpen((open) => !open);
          }}
        >
          ＋ 患者を追加
        </button>
      </div>
      {formOpen ? (
        <div id="d-patient-add-form">
          <PatientCreateForm
            busy={creating}
            onCreate={(regimen) => void handleCreate(regimen)}
            onCancel={() => setFormOpen(false)}
          />
        </div>
      ) : null}
      {createdId ? (
        <p role="status" className="d-ok">
          {createdId} を追加しました。登録用QRを患者に読み取ってもらいます。
        </p>
      ) : null}
      {createError ? (
        <ErrorNote code={createError} prefix="追加できませんでした" />
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
