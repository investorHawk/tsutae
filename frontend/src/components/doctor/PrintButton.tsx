import { useEffect, useRef, useState } from "react";

/** iframe の読み込みを待つ上限（ms）。過ぎたら別タブで開く案内に戻す。 */
export const PRINT_LOAD_TIMEOUT_MS = 15_000;

/** 印刷の案内。行ごとにくり返さず、印刷待ちの表の上に1回だけ出す（D2-1）。 */
export const PRINT_HINT =
  "印刷ダイアログが開きます。開かなければ『レポートを開く』から ⌘P";

type Status = "idle" | "loading" | "opened" | "failed";

/**
 * レポート（text/html。CSP で script が動かない）を同じオリジンの非表示 iframe に読み込み、
 * load の後に親から contentWindow.print() を呼ぶ。読み込めない・HTML でない（ログイン切れの
 * JSON 等）・print が投げた・時間切れなら、別タブで開くリンクから印刷するよう案内する。
 * iframe は display:none にしない（ブラウザによっては空白を印刷する）。印刷の後も残す
 * （print の直後に消すと印刷が取り消されるブラウザがある）。
 */
export default function PrintButton({
  url,
  disabled = false,
}: {
  url: string;
  /** 同じ行の「AI でもう一度変換」を依頼している間は押せない */
  disabled?: boolean;
}) {
  const [round, setRound] = useState(0);
  const [status, setStatus] = useState<Status>("idle");
  const frameRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (status !== "loading") {
      return undefined;
    }
    const timer = setTimeout(() => setStatus("failed"), PRINT_LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [status, round]);

  function start() {
    setRound((n) => n + 1);
    setStatus("loading");
  }

  function handleLoad() {
    if (status !== "loading") {
      return;
    }
    try {
      const win = frameRef.current?.contentWindow;
      const doc = frameRef.current?.contentDocument;
      if (!win || !doc || doc.contentType !== "text/html") {
        throw new Error("report is not an HTML document");
      }
      win.focus();
      win.print();
      setStatus("opened");
    } catch (err) {
      console.error("印刷ダイアログを開けませんでした", err);
      setStatus("failed");
    }
  }

  return (
    <span className="d-print">
      <button
        type="button"
        className="d-linkbutton d-linkbutton--primary"
        disabled={disabled || status === "loading"}
        onClick={start}
      >
        印刷
      </button>
      <a
        className="d-sublink"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
      >
        レポートを開く
      </a>
      {status === "failed" ? (
        <span role="alert" className="d-error">
          印刷ダイアログを開けませんでした。『レポートを開く』から ⌘P
          で印刷してください
        </span>
      ) : null}
      {round > 0 ? (
        <iframe
          key={round}
          ref={frameRef}
          className="d-print-frame"
          src={url}
          title="印刷用のレポート"
          aria-hidden="true"
          tabIndex={-1}
          onLoad={handleLoad}
        />
      ) : null}
    </span>
  );
}
