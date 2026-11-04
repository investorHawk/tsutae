import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePolling } from "./usePolling";

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"],
  });
});

afterEach(() => {
  vi.useRealTimers();
});

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("usePolling", () => {
  it("すぐに1回取り、その後は間隔ごとに取り直す", async () => {
    const fetcher = vi.fn(async () => "a");
    const { result } = renderHook(() => usePolling(fetcher, 5000));
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe("a");
    await flush(4999);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("前の取得が終わるまで次を始めない", async () => {
    let resolve: (value: string) => void = () => {};
    const fetcher = vi.fn(() => new Promise<string>((r) => (resolve = r)));
    renderHook(() => usePolling(fetcher, 1000));
    await flush(5000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => resolve("x"));
    await flush(1000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("shouldStop が true を返したら止める", async () => {
    const values = ["generating", "ready"];
    const fetcher = vi.fn(async () => values.shift() ?? "ready");
    const { result } = renderHook(() =>
      usePolling(fetcher, 2000, { shouldStop: (v) => v === "ready" }),
    );
    await flush();
    expect(result.current.stopped).toBe(false);
    await flush(2000);
    expect(result.current.data).toBe("ready");
    expect(result.current.stopped).toBe(true);
    await flush(10_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("失敗しても前のデータを残して続け、成功したら error を消す", async () => {
    const fetcher = vi
      .fn<() => Promise<string>>()
      .mockResolvedValueOnce("a")
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue("b");
    const { result } = renderHook(() => usePolling(fetcher, 1000));
    await flush();
    await flush(1000);
    expect(result.current.data).toBe("a");
    expect(result.current.error).toBeInstanceOf(Error);
    await flush(1000);
    expect(result.current.data).toBe("b");
    expect(result.current.error).toBeNull();
  });

  it("onError が true を返したら止める", async () => {
    const fetcher = vi.fn(async () => {
      throw new Error("unauthorized");
    });
    const onError = vi.fn(() => true);
    const { result } = renderHook(() => usePolling(fetcher, 1000, { onError }));
    await flush();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(result.current.stopped).toBe(true);
    await flush(5000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("refresh ですぐ取り直す", async () => {
    const fetcher = vi.fn(async () => "a");
    const { result } = renderHook(() => usePolling(fetcher, 5000));
    await flush();
    act(() => result.current.refresh());
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
    await flush(4999);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await flush(1);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("enabled が false なら取らない", async () => {
    const fetcher = vi.fn(async () => "a");
    renderHook(() => usePolling(fetcher, 1000, { enabled: false }));
    await flush(5000);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("アンマウントしたら止める", async () => {
    const fetcher = vi.fn(async () => "a");
    const { unmount } = renderHook(() => usePolling(fetcher, 1000));
    await flush();
    unmount();
    await flush(5000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
