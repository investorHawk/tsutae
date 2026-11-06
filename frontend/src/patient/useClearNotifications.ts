import { useEffect } from "react";
import { clearDeliveredNotifications } from "./pushDevice";

/** アプリを開いたとき・戻ってきたときに、バッジと表示中の通知を消す。 */
export function useClearNotifications(): void {
  useEffect(() => {
    void clearDeliveredNotifications();
    const onChange = () => {
      if (document.visibilityState === "visible") {
        void clearDeliveredNotifications();
      }
    };
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
}
