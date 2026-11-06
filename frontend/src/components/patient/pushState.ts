/** 通知の状態を読む（設定の画面と今日の記録の帯が使う）。何も登録せず、許可も求めない。 */
import { getPushConfig } from "../../api/patientPush";
import { currentPermission, findSubscription } from "../../patient/pushDevice";
import { pushStatusOf, type PushStatus } from "./pushStatus";

export interface PushState {
  /** サーバーの公開鍵。通知を使えないときは null */
  publicKey: string | null;
  permission: NotificationPermission;
  subscription: PushSubscription | null;
}

/** 通知に対応した端末でだけ呼ぶ（isPushSupported）。 */
export async function loadPushState(): Promise<PushState> {
  const config = await getPushConfig();
  const publicKey = config.available ? config.public_key : null;
  const subscription =
    publicKey === null ? null : await findSubscription(publicKey);
  return { publicKey, permission: currentPermission(), subscription };
}

export function statusOfState(state: PushState): PushStatus {
  return pushStatusOf({
    supported: true,
    hasKey: state.publicKey !== null,
    permission: state.permission,
    subscribed: state.subscription !== null,
  });
}
