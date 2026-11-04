import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { errorCode, isUnauthorized } from "./errors";

/**
 * 医師 API の失敗を code にする。401 ならログイン画面へ移す（state.from に今の経路）。
 * RequireDoctor は最初の確認しかしないので、後から切れたセッションはここで扱う。
 */
export function useDoctorApiError(): (err: unknown) => string {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return useCallback(
    (err: unknown) => {
      if (isUnauthorized(err)) {
        navigate("/doctor/login", { replace: true, state: { from: pathname } });
      }
      return errorCode(err);
    },
    [navigate, pathname],
  );
}
