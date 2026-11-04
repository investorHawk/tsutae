import { useCallback, useEffect, useState } from "react";
import { listRegimens } from "../../../api/doctor";
import { listRegimenDrafts } from "../../../api/regimenDrafts";
import type { RegimenDraftSummary } from "../../../api/regimenTypes";
import type { RegimenChoice } from "../../../api/types";

export interface RegimenCatalog {
  /** 採用済みのレジメン（GET /regimens。FOLFOX・CAPOX が先） */
  regimens: RegimenChoice[];
  /** 開いている下書き（GET /regimen-drafts） */
  drafts: RegimenDraftSummary[];
  error: string | null;
  reload: () => Promise<void>;
}

/** D4 レジメンのタブの元（採用済みの一覧と開いている下書き）。開いた時と採用・破棄の後に読む。 */
export function useRegimenCatalog(
  handleError: (err: unknown) => string,
): RegimenCatalog {
  const [regimens, setRegimens] = useState<RegimenChoice[]>([]);
  const [drafts, setDrafts] = useState<RegimenDraftSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [r, d] = await Promise.all([listRegimens(), listRegimenDrafts()]);
      setRegimens(r.regimens);
      setDrafts(d.drafts);
      setError(null);
    } catch (err) {
      setError(handleError(err));
    }
  }, [handleError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { regimens, drafts, error, reload };
}
