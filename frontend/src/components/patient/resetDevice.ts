/**
 * このスマホの登録と記録を消す手順（docs/plan-device-records.md §5.9）。文面は持たない。
 * 1つが失敗しても次へ進む（圏外でも端末の記録と仮名ID は消せる）。日付の印は消さない。
 */
import { unregisterPatient } from "../../api/patientDevice";
import { deleteDeviceEntries } from "../../patient/deviceStore";
import { clearPid } from "../../patient/pid";
import {
  currentSubscription,
  isStillSubscribed,
} from "../../patient/pushDevice";
import { isNotRegistered } from "./patientApi";
import { pushWritesSettled } from "./pushResend";

/** Cookie がもう無ければ（401・403）、消す相手も無いので成功と同じ。 */
async function unregisterOnServer(
  pid: string,
  endpoint: string | null,
): Promise<void> {
  try {
    await unregisterPatient(pid, endpoint);
  } catch (err) {
    if (!isNotRegistered(err)) {
      throw err;
    }
  }
}

/** false は「解除できなかった」か「もう解除されていた」。端末に残っているときだけ失敗にする。 */
async function removeFromBrowser(
  subscription: PushSubscription | null,
): Promise<void> {
  if (!subscription) {
    return;
  }
  const removed = await subscription.unsubscribe();
  if (!removed && (await isStillSubscribed(subscription.endpoint))) {
    throw new Error("unsubscribe failed");
  }
}

async function succeeded(step: () => Promise<void>): Promise<boolean> {
  try {
    await step();
    return true;
  } catch {
    return false;
  }
}

/**
 * サーバーの登録 → ブラウザの通知の登録 → 端末の記録 → 仮名ID の順に消す。全て消せたら true。
 * false でも仮名ID は消えている。呼ぶ側が同じ pid で押し直せる（Cookie が消えた後は成功と同じ）。
 * 先に送り直しの PUT を待つ（消した後に届いて、サーバーの登録が戻らないように）。
 */
export async function resetDevice(pid: string): Promise<boolean> {
  await pushWritesSettled();
  const subscription = await currentSubscription().catch(() => undefined);
  const results = [
    subscription !== undefined,
    await succeeded(() =>
      unregisterOnServer(pid, subscription?.endpoint ?? null),
    ),
    await succeeded(() => removeFromBrowser(subscription ?? null)),
    await succeeded(() => deleteDeviceEntries(pid)),
  ];
  clearPid();
  return results.every(Boolean);
}
