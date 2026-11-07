import { useEffect, useRef } from "react";
import { getQuestions } from "../../api/patient";
import { onOpenTodayMessage } from "../../patient/pushDevice";

/**
 * 開いたまま日付が変わった画面に気づく。戻ったとき・通知を押したときに質問集を読み、
 * 画面が持つ今日とサーバーの今日が違えば onNewDay を呼ぶ。同じ日なら何も起こさない
 * （書きかけを消さない）。読めないときは今の画面のまま（記録の邪魔をしない）。
 */
export function useNewDayCheck(
  pid: string | null,
  today: string | null,
  onNewDay: () => void,
): void {
  const latest = useRef({ today, onNewDay });
  useEffect(() => {
    latest.current = { today, onNewDay };
  });

  useEffect(() => {
    if (!pid) {
      return;
    }
    let active = true;
    let checking = false;
    const check = async () => {
      const shown = latest.current.today;
      if (shown === null || checking) {
        return;
      }
      checking = true;
      try {
        const server = await getQuestions(pid);
        if (
          active &&
          server.today !== shown &&
          latest.current.today === shown
        ) {
          latest.current.onNewDay();
        }
      } catch {
        // 次に戻ったときにまた確かめる
      } finally {
        checking = false;
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void check();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    const stopMessages = onOpenTodayMessage(() => void check());
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", onVisibility);
      stopMessages();
    };
  }, [pid]);
}
