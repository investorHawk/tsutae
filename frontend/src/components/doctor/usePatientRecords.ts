import { useEffect, useState } from "react";
import { listPatientEntries, listPatientVisits } from "../../api/doctor";
import type {
  DoctorEntry,
  PatientEntriesSummaryResponse,
  PatientVisit,
} from "../../api/types";

/** 読み込み前は null。失敗は error（code）に入れ、もう片方の節は止めない。 */
export interface Loadable<T> {
  value: T | null;
  error: string | null;
}

export interface PatientRecords {
  visits: Loadable<PatientVisit[]>;
  entries: Loadable<{ items: DoctorEntry[]; total: number }>;
}

const LOADING = { value: null, error: null };

/**
 * D2 の患者の受診と直近の記録を1回ずつ取る。患者を変えたら画面ごと描き直す前提
 * （PatientDetail が key={pid} で描く）。外した後の応答は捨てる。
 */
export function usePatientRecords(
  pid: string,
  handleError: (err: unknown) => string,
): PatientRecords {
  const [visits, setVisits] = useState<Loadable<PatientVisit[]>>(LOADING);
  const [entries, setEntries] = useState<PatientRecords["entries"]>(LOADING);

  useEffect(() => {
    let active = true;
    listPatientVisits(pid)
      .then((res) => {
        if (active) {
          setVisits({ value: res.visits, error: null });
        }
      })
      .catch((err: unknown) => {
        const code = handleError(err);
        if (active) {
          setVisits({ value: null, error: code });
        }
      });
    listPatientEntries(pid)
      .then((res: PatientEntriesSummaryResponse) => {
        if (active) {
          setEntries({
            value: { items: res.entries, total: res.total },
            error: null,
          });
        }
      })
      .catch((err: unknown) => {
        const code = handleError(err);
        if (active) {
          setEntries({ value: null, error: code });
        }
      });
    return () => {
      active = false;
    };
  }, [pid, handleError]);

  return { visits, entries };
}
