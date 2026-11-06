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
import { isApiError } from "../../api/http";
import { isNotRegistered } from "./patientApi";
import { pushWritesSettled } from "./pushResend";

export interface ResetResult {
  /** 全て消せたか */
  cleared: boolean;
  /** サーバーへ送った通知の endpoint。押し直しのときに渡す */
  endpoint: string | null;
}

/** DB にこの患者がいない（別の DB で起動した）。proxy などの 404 と分けるため code も見る。 */
function isUnknownPatient(err: unknown): boolean {
  return (
    isApiError(err) && err.status === 404 && err.code === "unknown_patient"
  );
}

/**
 * Cookie がもう無い（401・403）か、DB に患者がいない（404）なら、消す相手も無いので成功と同じ。
 * 404 のときは Cookie が残るが、仮名ID が無いので使われず、次の登録で上書きされる。
 */
async function unregisterOnServer(
  pid: string,
  endpoint: string | null,
): Promise<void> {
  try {
    await unregisterPatient(pid, endpoint);
  } catch (err) {
    if (!isNotRegistered(err) && !isUnknownPatient(err)) {
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
 * サーバーの登録 → ブラウザの通知の登録 → 端末の記録 → 仮名ID の順に消す。
 * 消せなくても仮名ID は消えている。呼ぶ側が同じ pid と前の endpoint で押し直せる（Cookie が
 * 消えた後は成功と同じ）。前の回でブラウザの登録を解除していると endpoint はもう読めないので、
 * 渡された knownEndpoint を送る（サーバーの行を残さないように）。
 * 先に送り直しの PUT を待つ（消した後に届いて、サーバーの登録が戻らないように）。
 */
export async function resetDevice(
  pid: string,
  knownEndpoint: string | null = null,
): Promise<ResetResult> {
  await pushWritesSettled();
  const subscription = await currentSubscription().catch(() => undefined);
  const endpoint = subscription?.endpoint ?? knownEndpoint;
  const results = [
    subscription !== undefined,
    await succeeded(() => unregisterOnServer(pid, endpoint)),
    await succeeded(() => removeFromBrowser(subscription ?? null)),
    await succeeded(() => deleteDeviceEntries(pid)),
  ];
  clearPid();
  return { cleared: results.every(Boolean), endpoint };
}
