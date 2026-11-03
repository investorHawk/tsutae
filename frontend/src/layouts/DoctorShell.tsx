import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { logout } from "../api/doctor";
import ErrorBoundary from "../components/ErrorBoundary";
import DoctorCrash from "../components/doctor/DoctorCrash";
import ErrorNote from "../components/doctor/ErrorNote";
import { errorCode, isUnauthorized } from "../components/doctor/errors";

/**
 * ログイン後の医師画面の枠（上部のナビゲーション）。
 * ログアウトはサーバーが成功を返した時だけログイン画面へ移す。失敗したら Cookie が
 * 残っているので、この画面に留まって失敗を出す（院内の共有 PC で開き直されないように）。
 * 401 はセッションがもう切れているので、ログイン画面へ移してよい。
 */
export default function DoctorShell() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    setLogoutError(null);
    try {
      await logout();
    } catch (err) {
      if (!isUnauthorized(err)) {
        setLogoutError(errorCode(err));
        setLoggingOut(false);
        return;
      }
    }
    navigate("/doctor/login", { replace: true });
  }

  return (
    <>
      <header className="doctor-header">
        <span className="doctor-brand">つたえ（院内）</span>
        <nav className="doctor-nav" aria-label="医師メニュー">
          <NavLink to="/doctor" end>
            印刷待ち
          </NavLink>
          <NavLink to="/doctor/patients">患者</NavLink>
          <NavLink to="/doctor/settings">設定を変える</NavLink>
        </nav>
        <button
          type="button"
          className="doctor-logout"
          disabled={loggingOut}
          onClick={() => void handleLogout()}
        >
          ログアウト
        </button>
      </header>
      {logoutError ? (
        <ErrorNote code={logoutError} prefix="ログアウトできませんでした" />
      ) : null}
      <main className="doctor-main">
        <ErrorBoundary resetKey={pathname} fallback={<DoctorCrash />}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}
