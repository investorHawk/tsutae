import { Outlet, useLocation } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary";
import { ErrorMessage } from "../components/patient/Messages";
import { GENERIC_ERROR_KEY } from "../components/patient/patientApi";
import {
  PatientStringsProvider,
  usePatientStrings,
} from "../strings/PatientStrings";

/**
 * 患者ルートの外枠。定型文を一度読み、スマホ向けの見た目（patient.css）で包む。
 * ページの描画で例外が出たら error.generic だけを出す（真っ白にしない。経路が変われば戻る）。
 */
/** 全ての患者画面の下に出す「症例は全て架空」の注記（登録画面は本文に出すので除く） */
function SyntheticNotice({ pathname }: { pathname: string }) {
  const { t } = usePatientStrings();
  if (pathname.startsWith("/register")) return null;
  return <p className="p-synthetic">{t("app.notice_synthetic")}</p>;
}

export default function PatientLayout() {
  const { pathname } = useLocation();
  return (
    <PatientStringsProvider>
      <div className="patient-app">
        <main className="patient-main">
          <ErrorBoundary
            resetKey={pathname}
            fallback={<ErrorMessage messageKey={GENERIC_ERROR_KEY} />}
          >
            <Outlet />
          </ErrorBoundary>
        </main>
        <SyntheticNotice pathname={pathname} />
      </div>
    </PatientStringsProvider>
  );
}
