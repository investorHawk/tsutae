import { describe, expect, it } from "vitest";
import {
  DEFAULT_NOTIFY_TIME,
  NOTIFY_TIMES,
  isNotifyTime,
  pushStatusOf,
  type PushFacts,
  type PushStatus,
} from "./pushStatus";

const USABLE: PushFacts = {
  supported: true,
  hasKey: true,
  permission: "default",
  subscribed: false,
};

describe("pushStatusOf", () => {
  const cases: [string, Partial<PushFacts>, PushStatus][] = [
    ["未対応の端末", { supported: false }, "unsupported"],
    [
      "未対応が先（鍵も無い）",
      { supported: false, hasKey: false },
      "unsupported",
    ],
    [
      "未対応が先（拒否もしている）",
      { supported: false, permission: "denied" },
      "unsupported",
    ],
    ["鍵なし", { hasKey: false }, "no_key"],
    ["鍵なしが拒否より先", { hasKey: false, permission: "denied" }, "no_key"],
    ["拒否済み", { permission: "denied" }, "denied"],
    [
      "登録が残っていても拒否済み",
      { permission: "denied", subscribed: true },
      "denied",
    ],
    ["許可あり・登録あり", { permission: "granted", subscribed: true }, "on"],
    ["許可あり・登録なし", { permission: "granted" }, "off"],
    ["未確認・登録なし", {}, "off"],
    ["許可が消えて登録だけ残る", { subscribed: true }, "off"],
  ];

  it.each(cases)("%s", (_label, facts, expected) => {
    expect(pushStatusOf({ ...USABLE, ...facts })).toBe(expected);
  });
});

describe("notify times", () => {
  it("00:00 から 23:30 まで 30 分刻みの 48 個", () => {
    expect(NOTIFY_TIMES).toHaveLength(48);
    expect(NOTIFY_TIMES[0]).toBe("00:00");
    expect(NOTIFY_TIMES[1]).toBe("00:30");
    expect(NOTIFY_TIMES[47]).toBe("23:30");
    expect(new Set(NOTIFY_TIMES).size).toBe(48);
  });

  it("既定は 20:00 で、選べる時刻に入っている", () => {
    expect(DEFAULT_NOTIFY_TIME).toBe("20:00");
    expect(NOTIFY_TIMES).toContain(DEFAULT_NOTIFY_TIME);
  });

  it.each([
    ["20:00", true],
    ["08:30", true],
    ["20:15", false],
    ["24:00", false],
    ["8:00", false],
    ["", false],
    [null, false],
  ])("isNotifyTime(%s) = %s", (value, expected) => {
    expect(isNotifyTime(value)).toBe(expected);
  });
});
