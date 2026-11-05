import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch } from "../../../test/fetchMock";
import { deferred } from "../testing";
import { useRegimenDrugNames } from "./useRegimenDrugNames";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRegimenDrugNames", () => {
  it("開いたときに1回読む", async () => {
    const mock = mockFetch(() => jsonResponse({ names: ["A"] }));
    const { result } = renderHook(() => useRegimenDrugNames());
    expect(result.current.names).toEqual([]);
    await waitFor(() => expect(result.current.names).toEqual(["A"]));
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("読み直しに失敗しても今の候補のまま（例外を外へ出さない）", async () => {
    let ok = true;
    mockFetch(() =>
      ok
        ? jsonResponse({ names: ["A"] })
        : jsonResponse({ error: "internal_error" }, 500),
    );
    const { result } = renderHook(() => useRegimenDrugNames());
    await waitFor(() => expect(result.current.names).toEqual(["A"]));
    ok = false;
    await act(async () => {
      await expect(result.current.reload()).resolves.toBeUndefined();
    });
    expect(result.current.names).toEqual(["A"]);
  });

  it("遅れて返った古い応答で新しい候補を上書きしない", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const gates = [first, second];
    mockFetch(() => gates.shift()!.promise);
    const { result } = renderHook(() => useRegimenDrugNames());
    let reloaded: Promise<void> = Promise.resolve();
    act(() => {
      reloaded = result.current.reload();
    });
    await act(async () => {
      second.resolve(jsonResponse({ names: ["新しい"] }));
      await reloaded;
    });
    expect(result.current.names).toEqual(["新しい"]);
    await act(async () => {
      first.resolve(jsonResponse({ names: ["古い"] }));
      await first.promise;
      await Promise.resolve();
    });
    expect(result.current.names).toEqual(["新しい"]);
  });
});
