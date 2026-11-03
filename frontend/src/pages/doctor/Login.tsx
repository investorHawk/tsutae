import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { login } from "../../api/doctor";
import { isApiError } from "../../api/http";
import ErrorNote from "../../components/doctor/ErrorNote";
import { errorCode } from "../../components/doctor/errors";
import { safeDoctorPath } from "../../components/doctor/input";
import "../../components/doctor/doctor-ui.css";

type LoginError = { kind: "wrong" } | { kind: "other"; code: string };

/** 医師のログイン（デモ用の単一パスワード）。開いただけでは API を呼ばない。 */
export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<LoginError | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password === "" || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(password);
      navigate(safeDoctorPath(location.state), { replace: true });
    } catch (err) {
      const wrong =
        isApiError(err) && (err.status === 401 || err.status === 403);
      setError(
        wrong ? { kind: "wrong" } : { kind: "other", code: errorCode(err) },
      );
      setBusy(false);
    }
  }

  return (
    <section className="page d-login">
      <h1>ログイン</h1>
      <p className="d-muted">つたえ 医師画面（院内）</p>
      <form className="d-login-form" onSubmit={(e) => void handleSubmit(e)}>
        <label className="d-field">
          <span>パスワード</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />
        </label>
        <button
          type="submit"
          className="d-primary"
          disabled={password === "" || busy}
        >
          ログイン
        </button>
      </form>
      {error?.kind === "wrong" ? (
        <p role="alert" className="d-error">
          パスワードが違います
        </p>
      ) : null}
      {error?.kind === "other" ? (
        <ErrorNote code={error.code} prefix="ログインできませんでした" />
      ) : null}
    </section>
  );
}
