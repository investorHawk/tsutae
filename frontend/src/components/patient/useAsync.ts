import { useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: unknown };

/** key が変わるたびに load を呼ぶ。外れた（unmount・key 変更）結果は捨てる。 */
export function useAsync<T>(
  load: () => Promise<T>,
  key: string,
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

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
  }, [key]);

  return state;
}
