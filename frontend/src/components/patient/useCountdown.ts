import { useEffect, useRef, useState } from "react";

/**
 * active の間、seconds から1秒ごとに数を減らし、0 になったら onDone を1回だけ呼ぶ。
 * active が false になる・unmount するとタイマーを止める（次に active になったら最初から）。
 * 返すのは残りの秒数（表示用。seconds → … → 1）。
 */
export function useCountdown(
  active: boolean,
  seconds: number,
  onDone: () => void,
): number {
  const [left, setLeft] = useState(seconds);
  const onDoneRef = useRef(onDone);

  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    if (!active) {
      return;
    }
    let remaining = seconds;
    setLeft(remaining);
    const timer = window.setInterval(() => {
      remaining -= 1;
      if (remaining > 0) {
        setLeft(remaining);
        return;
      }
      window.clearInterval(timer);
      onDoneRef.current();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active, seconds]);

  return left;
}
