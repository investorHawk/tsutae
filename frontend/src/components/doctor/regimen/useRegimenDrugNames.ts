import { useCallback, useEffect, useRef, useState } from "react";
import { listRegimenDrugNames } from "../../../api/regimenDrafts";

export interface RegimenDrugNames {
  names: readonly string[];
  reload: () => Promise<void>;
}

/**
 * 薬の名前の候補。D4 の画面を開いた時に1回読み、採用の後に読み直す。候補は入力の補助なので、
 * 読めなくても知らせない（初めは候補なし、読み直しの失敗は今の候補のまま）。
 */
export function useRegimenDrugNames(): RegimenDrugNames {
  const [names, setNames] = useState<readonly string[]>([]);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    latest.current += 1;
    const asked = latest.current;
    try {
      const body = await listRegimenDrugNames();
      if (asked === latest.current) {
        setNames(body.names);
      }
    } catch {
      // handleError に渡さない（補助のデータの失敗で画面を止めない）
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { names, reload };
}
