import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { checkDoctorSession } from "../api/doctor";

type SessionState = "checking" | "ok" | "login";

/**
 * ログイン済みの医師だけを通す。確認は医師 API の 401 で行う（§8 に専用の経路が無い）。
 * 未ログインなら /doctor/login へ（state.from に元の経路）。401 以外の失敗は通して、
 * 扱いを各ページに任せる。ページの API が後から 401 を返したら、ページ側で
 * /doctor/login へ移す。
 */
export default function RequireDoctor() {
  const location = useLocation();
  const [state, setState] = useState<SessionState>("checking");

  useEffect(() => {
    let active = true;
    checkDoctorSession()
      .then((ok) => {
        if (active) {
          setState(ok ? "ok" : "login");
        }
      })
      .catch((err: unknown) => {
        console.error("ログイン状態を確認できませんでした", err);
        if (active) {
          setState("ok");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  if (state === "checking") {
    return null;
  }
  if (state === "login") {
    return (
      <Navigate
        to="/doctor/login"
        replace
        state={{ from: location.pathname }}
      />
    );
  }
  return <Outlet />;
}
