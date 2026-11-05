import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import AddToHomeGuide from "../components/patient/AddToHomeGuide";
import ErrorBoundary from "../components/ErrorBoundary";
import { ErrorMessage } from "../components/patient/Messages";
import { GENERIC_ERROR_KEY } from "../components/patient/patientApi";
import { useResendSubscription } from "../components/patient/pushResend";
import {
  needsHomeScreenGuide,
  readDisplayEnv,
  suggestsHomeScreen,
} from "../patient/standalone";
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
 * 全ての患者画面の下に出す「症例は全て架空」の注記。
 * 本文（patient-main）の外にあるので、同じ幅と左右の余白の枠（patient-footer）に入れる。
 */
function SyntheticNotice() {
  const { t } = usePatientStrings();
  return (
    <div className="patient-footer">
      <p className="p-synthetic">{t("app.notice_synthetic")}</p>
    </div>
  );
}

/** Android のブラウザにだけ、ホーム画面への追加を勧める1行（§5.8）。 */
function HomeScreenSuggestion() {
  const { t } = usePatientStrings();
  return <p className="p-hint">{t("guide.suggest")}</p>;
}

/**
 * アプリを開いたらバッジと表示中の通知を消し、オンの端末の登録を送り直す（医師の画面はこの
 * 外枠を通らない）。定型文を待たずに始める（設定の画面は、この送り直しを待って状態を読む）。
 */
function DeviceUpkeep() {
  useClearNotifications();
  useResendSubscription();
  return null;
}

/**
 * 下のタブ（PatientNav。画面の下に固定）のある画面は patient-app--with-nav で
 * 下をあける（本文の最後がタブに隠れないように）。
 */
function PatientScreens({ suggestHome }: { suggestHome: boolean }) {
  const { pathname } = useLocation();
  const withNav = !isRegister(pathname);
  return (
    <div className={`patient-app${withNav ? " patient-app--with-nav" : ""}`}>
      <main className="patient-main">
        {suggestHome && <HomeScreenSuggestion />}
        <ErrorBoundary
          resetKey={pathname}
          fallback={<ErrorMessage messageKey={GENERIC_ERROR_KEY} />}
        >
          <Outlet />
        </ErrorBoundary>
      </main>
      {/* 登録画面は本文に出す */}
      {!isRegister(pathname) && <SyntheticNotice />}
    </div>
  );
}

/** iPhone のブラウザの画面（案内だけ。記録も API の呼び出しも通知の処理もしない）。 */
function GuideScreen() {
  return (
    <div className="patient-app">
      <main className="patient-main">
        <AddToHomeGuide />
      </main>
      <SyntheticNotice />
    </div>
  );
}

export default function PatientLayout() {
  const [env] = useState(readDisplayEnv);
  if (needsHomeScreenGuide(env)) {
    return (
      <PatientStringsProvider>
        <GuideScreen />
      </PatientStringsProvider>
    );
  }
  return (
    <>
      <DeviceUpkeep />
      <PatientStringsProvider>
        <PatientScreens suggestHome={suggestsHomeScreen(env)} />
      </PatientStringsProvider>
    </>
  );
}
