import { describe, expect, it } from "vitest";
import { nextTabIndex } from "./tabKeys";

describe("nextTabIndex", () => {
  it("← → で隣へ。端では反対の端へ回る", () => {
    expect(nextTabIndex("ArrowRight", 0, 3)).toBe(1);
    expect(nextTabIndex("ArrowRight", 2, 3)).toBe(0);
    expect(nextTabIndex("ArrowLeft", 0, 3)).toBe(2);
    expect(nextTabIndex("ArrowLeft", 2, 3)).toBe(1);
  });

  it("Home・End で端へ。ほかのキー・タブが無いときは移らない", () => {
    expect(nextTabIndex("Home", 2, 3)).toBe(0);
    expect(nextTabIndex("End", 0, 3)).toBe(2);
    expect(nextTabIndex("Enter", 0, 3)).toBeNull();
    expect(nextTabIndex("ArrowRight", 0, 0)).toBeNull();
  });
});
