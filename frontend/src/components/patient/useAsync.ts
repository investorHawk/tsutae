import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: unknown };

/** 状態と、もう一度読む関数（読み込みの失敗の「読み直す」）。 */
export type AsyncResult<T> = AsyncState<T> & { reload: () => void };

/**
 * key が変わるたび・reload のたびに load を呼ぶ。外れた（unmount・key 変更・読み直し）
 * 結果は捨てる。
 */
export function useAsync<T>(
  load: () => Promise<T>,
  key: string,
): AsyncResult<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [round, setRound] = useState(0);

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    load().then(
      (data) => {
        if (active) {
          setState({ status: "ready", data });
        }
      },
      (error: unknown) => {
        if (active) {
          setState({ status: "error", error });
        }
      },
    );
    return () => {
      active = false;
    };
    // load は key ごとに同じ処理を表す（呼び出し側の関数の作り直しでは読み直さない）
  }, [key, round]);

  const reload = useCallback(() => setRound((n) => n + 1), []);
  return { ...state, reload };
}
