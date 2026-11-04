import { usePatientStrings } from "../../strings/PatientStrings";
import { ErrorMessage } from "./Messages";

/** 読み込み中の知らせ（common.loading）。 */
export function Loading() {
  const { t } = usePatientStrings();
  return (
    <p className="p-loading" role="status">
      {t("common.loading")}
    </p>
  );
}

/** 読み込めなかった知らせ（common.load_failed）と「読み直す」（common.reload）。 */
export function LoadFailed({ onReload }: { onReload: () => void }) {
  const { t } = usePatientStrings();
  return (
    <div className="p-load-failed">
      <ErrorMessage messageKey="common.load_failed" />
      <button type="button" onClick={onReload}>
        {t("common.reload")}
      </button>
    </div>
  );
}
