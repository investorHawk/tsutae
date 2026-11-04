/**
 * 一定の間隔で取り直す（D3 は5秒、D5 は2秒）。前の取得が終わってから次の
 * タイマーを掛ける（重ならない）。アンマウントで止まる。
 * 値（data・error・updatedAt・stopped）はマウントの間の1つの対象のもの。取る対象
 * （D5 の受診など）が変わるなら、呼び出し側が key を変えて描き直す（Pipeline.tsx）。
 * 前の対象の値を新しい対象の見出しの下に残さないため。
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface PollingOptions<T> {
  /** true を返したらそれ以上取らない（D5 の ready / failed）。 */
  shouldStop?: (data: T) => boolean;
  /** 失敗のたびに呼ぶ。true を返したら止める（401 でログイン画面へ移すとき）。 */
  onError?: (err: unknown) => boolean | void;
  /** false の間は取らない（経路の値が不正なとき）。既定 true。 */
  enabled?: boolean;
}

export interface PollingState<T> {
  /** 最後に取れた値（失敗しても前の値を残す） */
  data: T | null;
  /** 最後の取得の失敗。成功したら null */
  error: unknown;
  /** 最後に取れた時刻（表示用） */
  updatedAt: Date | null;
  stopped: boolean;
  /** すぐに取り直し、間隔を数え直す。止まっていても再開する。 */
  refresh: () => void;
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  options: PollingOptions<T> = {},
): PollingState<T> {
  const enabled = options.enabled ?? true;
  const fetcherRef = useRef(fetcher);
  const optionsRef = useRef(options);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [stopped, setStopped] = useState(false);
  const [round, setRound] = useState(0);

  useEffect(() => {
    fetcherRef.current = fetcher;
    optionsRef.current = options;
  });

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setStopped(false);

    async function tick() {
      try {
        const value = await fetcherRef.current();
        if (!active) {
          return;
        }
        setData(value);
        setError(null);
        setUpdatedAt(new Date());
        if (optionsRef.current.shouldStop?.(value)) {
          setStopped(true);
          return;
        }
      } catch (err) {
        if (!active) {
          return;
        }
        setError(err);
        if (optionsRef.current.onError?.(err) === true) {
          setStopped(true);
          return;
        }
      }
      timer = setTimeout(() => void tick(), intervalMs);
    }

    void tick();
    return () => {
      active = false;
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [enabled, intervalMs, round]);

  const refresh = useCallback(() => setRound((n) => n + 1), []);
  return { data, error, updatedAt, stopped, refresh };
}
