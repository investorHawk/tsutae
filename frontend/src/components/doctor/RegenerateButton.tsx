import { useEffect, useRef, useState } from "react";

interface RegenerateButtonProps {
  /** 押したら呼ぶ。失敗の表示は呼び出し側で行う */
  onRegenerate: () => Promise<void>;
}

/**
 * 「AI でもう一度変換」（2段階の確認はしない）。送っている間は押せない。
 * 受け付けられた後は一覧の取り直しで行が「生成中」になり、このボタンは消える。
 */
export default function RegenerateButton({
  onRegenerate,
}: RegenerateButtonProps) {
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function run() {
    setBusy(true);
    try {
      await onRegenerate();
    } catch (err) {
      console.error("操作に失敗しました", err);
    } finally {
      if (mounted.current) {
        setBusy(false);
      }
    }
  }

  return (
    <button type="button" disabled={busy} onClick={() => void run()}>
      {busy ? "変換を依頼中…" : "AI でもう一度変換"}
    </button>
  );
}
