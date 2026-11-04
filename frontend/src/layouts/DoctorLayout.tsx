import { Outlet, useLocation } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary";
import DoctorCrash from "../components/doctor/DoctorCrash";

/**
 * 医師ルートの外枠（院内 PC 向けの見た目、doctor.css）。描画で例外が出たら失敗の知らせを
 * 出す（真っ白にしない。経路が変われば戻る）。ログイン後のページは DoctorShell の中でも
 * 受け止め、上部のメニューを残す。
 */
export default function DoctorLayout() {
  const { pathname } = useLocation();
  return (
    <div className="doctor-app">
      <ErrorBoundary resetKey={pathname} fallback={<DoctorCrash />}>
        <Outlet />
      </ErrorBoundary>
    </div>
  );
}
