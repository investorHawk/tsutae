import { useState } from "react";
import { getDemoConfig, getDemoEntries } from "../../api/patientDevice";
import { saveDeviceEntry } from "../../patient/deviceStore";
import { usePatientStrings } from "../../strings/PatientStrings";
import { DoneMessage, ErrorMessage } from "./Messages";
import { errorKeyOf } from "./patientApi";
import { SendingMessage } from "./TooSickButton";
import { useAsync } from "./useAsync";

/** 見本を端末に保存する。ID が決まっているので、押し直しても増えない。 */
async function saveDemoEntries(pid: string): Promise<void> {
  const { entries } = await getDemoEntries(pid);
  for (const entry of entries) {
    await saveDeviceEntry(entry);
  }
}

function DemoEntriesButton({ pid }: { pid: string }) {
  const { t } = usePatientStrings();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);

  async function add() {
    setBusy(true);
    setDone(false);
    setErrorKey(null);
    try {
      await saveDemoEntries(pid);
      setDone(true);
    } catch (err) {
      setErrorKey(errorKeyOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2>{t("demo.title")}</h2>
      {busy && <SendingMessage />}
      {done && <DoneMessage messageKey="demo.added" />}
      {errorKey && <ErrorMessage messageKey={errorKey} />}
      <button type="button" disabled={busy} onClick={add}>
        {t("demo.add_entries")}
      </button>
    </>
  );
}

/**
 * 設定の「見本の記録を入れる」（docs/plan-device-records.md §5.10）。サーバーが demo_tools を
 * 真と答えたときだけ出す。聞けなければ何も出さない（撮影の道具で画面を止めない）。
 */
export default function DemoEntries({ pid }: { pid: string }) {
  const config = useAsync(() => getDemoConfig(pid), pid);
  if (config.status !== "ready" || !config.data.demo_tools) {
    return null;
  }
  return <DemoEntriesButton pid={pid} />;
}
