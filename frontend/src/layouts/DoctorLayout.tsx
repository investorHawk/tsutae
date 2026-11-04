import { Outlet, useLocation } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary";
import DoctorCrash from "../components/doctor/DoctorCrash";

/** 医師画面の上端に常に出す注記（患者画面・レポートと同じ「症例は全て架空」） */
export const DOCTOR_SYNTHETIC_NOTICE =
  "デモ用の画面です。症例は全て架空（合成データ）です。";

/**
 * 医師ルートの外枠（院内 PC 向けの見た目、doctor.css）。描画で例外が出たら失敗の知らせを
 * 出す（真っ白にしない。経路が変われば戻る）。ログイン後のページは DoctorShell の中でも
 * 受け止め、上部のメニューを残す。
 * 架空の注記はログイン画面も含めて全ページの上端に置き、スクロールしても残す（デモ動画の
 * どの場面でも映るように）。
 */
export default function DoctorLayout() {
  const { pathname } = useLocation();
  return (
    <div className="doctor-app">
      <p className="doctor-synthetic" role="note">
        {DOCTOR_SYNTHETIC_NOTICE}
      </p>
      <ErrorBoundary resetKey={pathname} fallback={<DoctorCrash />}>
        <Outlet />
      </ErrorBoundary>
    </div>
  );
}
