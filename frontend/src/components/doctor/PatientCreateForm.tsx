import { useEffect, useState, type FormEvent } from "react";
import { listRegimens } from "../../api/doctor";
import { isRegimensResponse } from "../../api/doctorGuards";
import type { Regimen, RegimenChoice, RegimensResponse } from "../../api/types";
import { checked } from "../../api/validate";
import ErrorNote from "./ErrorNote";
import { useDoctorApiError } from "./useDoctorApiError";

interface PatientCreateFormProps {
  busy: boolean;
  onCreate: (regimen: Regimen) => void;
  /** 「やめる」で欄を閉じる */
  onCancel: () => void;
}

/**
 * D1 の「患者を追加」。小見出しつきの枠で一覧と分ける（D3-1）。仮名IDは無作為に作られる。
 * 普段は閉じていて、見出しの右の「＋ 患者を追加」で開く（Patients が出し入れする）。
 * レジメンの選択肢は GET /api/doctor/regimens（D4 で採用したレジメンも入る。T95）。
 * 表示名で並べ、識別名で送る。一覧を読めるまで「追加する」は押せない。
 */
export default function PatientCreateForm({
  busy,
  onCreate,
  onCancel,
}: PatientCreateFormProps) {
  const handleError = useDoctorApiError();
  const [choices, setChoices] = useState<RegimenChoice[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [regimen, setRegimen] = useState<Regimen>("");

  useEffect(() => {
    let alive = true;
    listRegimens()
      .then((body) => {
        const { regimens } = checked<RegimensResponse>(
          body,
          isRegimensResponse,
        );
        if (alive) {
          setChoices(regimens);
          setRegimen(regimens[0]?.code ?? "");
        }
      })
      .catch((err: unknown) => {
        if (alive) {
          setLoadError(handleError(err));
        }
      });
    return () => {
      alive = false;
    };
  }, [handleError]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (regimen) {
      onCreate(regimen);
    }
  }

  const ready = choices !== null && choices.length > 0 && regimen !== "";

  return (
    <section className="d-box d-patient-create" aria-labelledby="d-patient-add">
      <h2 id="d-patient-add">患者を追加</h2>
      <form className="d-inline-form" onSubmit={handleSubmit}>
        <label className="d-field d-field--inline">
          <span>レジメン</span>
          <select
            value={regimen}
            onChange={(e) => setRegimen(e.target.value)}
            disabled={choices === null}
          >
            {(choices ?? []).map((r) => (
              <option key={r.code} value={r.code}>
                {r.display_name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="d-primary" disabled={busy || !ready}>
          追加する
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          やめる
        </button>
      </form>
      {loadError && (
        <ErrorNote code={loadError} prefix="レジメンの一覧を読めませんでした" />
      )}
      {choices !== null && choices.length === 0 && (
        <p className="d-muted">選べるレジメンがありません</p>
      )}
      <p className="d-muted">
        仮名IDは無作為に作られます。対応表は院内の紙で管理します。追加すると登録用QRが出ます。
      </p>
    </section>
  );
}
