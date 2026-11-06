import { useState } from "react";
import DemoEntries from "../../components/patient/DemoEntries";
import DeviceReset from "../../components/patient/DeviceReset";
import { DoneMessage } from "../../components/patient/Messages";
import NotifySettings from "../../components/patient/NotifySettings";
import NotRegistered from "../../components/patient/NotRegistered";
import PatientNav from "../../components/patient/PatientNav";
import { loadPid } from "../../patient/pid";
import { usePatientStrings } from "../../strings/PatientStrings";

/**
 * P5 設定（/settings）。毎日のお知らせ・撮影用の見本（出してよいときだけ）・このスマホの登録と
 * 記録を消す。仮名ID が無ければ未登録の案内と番号の入力欄。消し始めたら他の操作は隠す
 * （消している途中に通知を登録し直さない）。消せたらその場で番号を入れ直せる。
 */
export default function Settings() {
  const { t } = usePatientStrings();
  const [pid] = useState(loadPid);
  const [resetting, setResetting] = useState(false);
  const [cleared, setCleared] = useState(false);
  return (
    <section className="page">
      <h1>{t("settings.title")}</h1>
      {cleared && <DoneMessage messageKey="device_reset.done" />}
      {pid && !cleared ? (
        <>
          {!resetting && <NotifySettings pid={pid} />}
          {!resetting && <DemoEntries pid={pid} />}
          <DeviceReset
            pid={pid}
            onStart={() => setResetting(true)}
            onCleared={() => setCleared(true)}
          />
        </>
      ) : (
        <NotRegistered />
      )}
      <PatientNav />
    </section>
  );
}
