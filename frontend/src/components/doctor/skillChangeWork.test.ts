import { describe, expect, it } from "vitest";
import type { SkillChange } from "../../api/types";
import {
  elapsedSeconds,
  findWorking,
  watchStartedAt,
  isWorking,
  settleWatched,
} from "./skillChangeWork";
import type { SkillPhase } from "./useSkillChangeFlow";

const DIFF = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n";

function change(patch: Partial<SkillChange>): SkillChange {
  return {
    id: 7,
    skill_name: "regimen-folfox",
    requested_text: "x",
    diff: null,
    status: "pending",
    base_version: 1,
    new_version: null,
    error_code: null,
    created_at: "2026-11-09T10:00:00+09:00",
    decided_at: null,
    ...patch,
  };
}

const WATCHING: SkillPhase = {
  kind: "generating",
  skillName: "regimen-folfox",
  startedAt: 0,
  changeId: 7,
};

describe("isWorking / findWorking", () => {
  it("pending で diff が無い行だけが作業中", () => {
    expect(isWorking(change({}))).toBe(true);
    expect(isWorking(change({ diff: DIFF }))).toBe(false);
    expect(isWorking(change({ diff: "" }))).toBe(false);
    expect(isWorking(change({ status: "failed" }))).toBe(false);
  });

  it("新しい順の一覧から最初の作業中を返す", () => {
    const list = [
      change({ id: 9, status: "failed" }),
      change({ id: 8 }),
      change({ id: 6 }),
    ];
    expect(findWorking(list)?.id).toBe(8);
    expect(findWorking([change({ diff: DIFF })])).toBeNull();
    expect(findWorking(null)).toBeNull();
  });
});

describe("settleWatched", () => {
  it("差分ができたら確認へ", () => {
    const next = settleWatched(WATCHING, [change({ diff: DIFF })]);
    expect(next).toEqual({
      kind: "review",
      target: {
        id: 7,
        skillName: "regimen-folfox",
        requestText: "x",
        diff: DIFF,
      },
      busy: false,
      error: null,
    });
  });

  it("まだ作業中・一覧に無いならそのまま（同じオブジェクト）", () => {
    expect(settleWatched(WATCHING, [change({})])).toBe(WATCHING);
    expect(settleWatched(WATCHING, [])).toBe(WATCHING);
  });

  it("失敗なら failed と error_code", () => {
    expect(
      settleWatched(WATCHING, [
        change({ status: "failed", error_code: "stale_request" }),
      ]),
    ).toEqual({ kind: "failed", changeId: 7, code: "stale_request" });
  });

  it("差分が空の pending は失敗として扱う（承認させない）", () => {
    expect(settleWatched(WATCHING, [change({ diff: "   " })])).toEqual({
      kind: "failed",
      changeId: 7,
      code: "skill_change_failed",
    });
  });

  it("ほかで承認・却下されたら入力に戻る", () => {
    expect(
      settleWatched(WATCHING, [change({ status: "rejected", diff: DIFF })]),
    ).toEqual({ kind: "input" });
  });

  it("見張っていない段階は変えない", () => {
    const own: SkillPhase = { ...WATCHING, changeId: null };
    expect(settleWatched(own, [change({ diff: DIFF })])).toBe(own);
    const input: SkillPhase = { kind: "input" };
    expect(settleWatched(input, [change({ diff: DIFF })])).toBe(input);
  });
});

describe("elapsedSeconds", () => {
  it("切り捨てた秒。負にしない", () => {
    expect(elapsedSeconds(1000, 4999)).toBe(3);
    expect(elapsedSeconds(5000, 1000)).toBe(0);
  });
});

describe("watchStartedAt", () => {
  const NOW = Date.parse("2026-11-09T10:00:30+09:00");

  it("created_at が少し前ならそこから数える", () => {
    expect(watchStartedAt("2026-11-09T10:00:00+09:00", NOW)).toBe(
      Date.parse("2026-11-09T10:00:00+09:00"),
    );
  });

  it("サーバーの時計がずれている（デモの固定日など）なら見張り始めから数える", () => {
    expect(watchStartedAt("2026-11-12T10:00:00+09:00", NOW)).toBe(NOW);
    expect(watchStartedAt("2026-11-01T10:00:00+09:00", NOW)).toBe(NOW);
    expect(watchStartedAt("not a date", NOW)).toBe(NOW);
  });
});
