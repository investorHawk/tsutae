import { Outlet, useLocation } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary";
import { ErrorMessage } from "../components/patient/Messages";
import { GENERIC_ERROR_KEY } from "../components/patient/patientApi";
import { useResendSubscription } from "../components/patient/pushResend";
import { useClearNotifications } from "../patient/useClearNotifications";
import {
  PatientStringsProvider,
  usePatientStrings,
} from "../strings/PatientStrings";

/**
 * 患者ルートの外枠。定型文を一度読み、スマホ向けの見た目（patient.css）で包む。
 * ページの描画で例外が出たら error.generic だけを出す（真っ白にしない。経路が変われば戻る）。
 */
/** 登録画面（下のタブが無く、架空の注記は本文に出す）。 */
function isRegister(pathname: string): boolean {
  return pathname.startsWith("/register");
}

/**
 * 全ての患者画面の下に出す「症例は全て架空」の注記（登録画面は本文に出すので除く）。
 * 本文（patient-main）の外にあるので、同じ幅と左右の余白の枠（patient-footer）に入れる。
 */
function SyntheticNotice({ pathname }: { pathname: string }) {
  const { t } = usePatientStrings();
  if (isRegister(pathname)) return null;
  return (
    <div className="patient-footer">
      <p className="p-synthetic">{t("app.notice_synthetic")}</p>
    </div>
  );
}

/**
 * 下のタブ（PatientNav。画面の下に固定）のある画面は patient-app--with-nav で
 * 下をあける（本文の最後がタブに隠れないように）。
 * アプリを開いたらバッジと表示中の通知を消し、オンの端末の登録を送り直す（医師の画面はこの
 * 外枠を通らない）。
 */
export default function PatientLayout() {
  const { pathname } = useLocation();
  const withNav = !isRegister(pathname);
  useClearNotifications();
  useResendSubscription();
  return (
    <PatientStringsProvider>
      <div className={`patient-app${withNav ? " patient-app--with-nav" : ""}`}>
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
