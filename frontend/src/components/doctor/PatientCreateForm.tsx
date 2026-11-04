import { useState, type FormEvent } from "react";
import { REGIMENS, type Regimen } from "../../api/types";

interface PatientCreateFormProps {
  busy: boolean;
  onCreate: (regimen: Regimen) => void;
}

/**
 * D1 の「患者を追加」。小見出しつきの枠で一覧と分ける（D3-1）。仮名IDは無作為に作られる。
 */
export default function PatientCreateForm({
  busy,
  onCreate,
}: PatientCreateFormProps) {
  const [regimen, setRegimen] = useState<Regimen>("FOLFOX");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onCreate(regimen);
  }

  return (
    <section className="d-box d-patient-create" aria-labelledby="d-patient-add">
      <h2 id="d-patient-add">患者を追加</h2>
      <form className="d-inline-form" onSubmit={handleSubmit}>
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
        <button type="submit" className="d-primary" disabled={busy}>
          患者を追加
        </button>
      </form>
      <p className="d-muted">
        仮名IDは無作為に作られます。対応表は院内の紙で管理します。追加すると登録用QRが出ます。
      </p>
    </section>
  );
}
