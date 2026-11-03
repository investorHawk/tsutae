import { Outlet, useLocation } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary";
import { ErrorMessage } from "../components/patient/Messages";
import { GENERIC_ERROR_KEY } from "../components/patient/patientApi";
import { PatientStringsProvider } from "../strings/PatientStrings";

/**
 * 患者ルートの外枠。定型文を一度読み、スマホ向けの見た目（patient.css）で包む。
 * ページの描画で例外が出たら error.generic だけを出す（真っ白にしない。経路が変われば戻る）。
 */
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
      </div>
    </PatientStringsProvider>
  );
}
