import { describe, expect, it } from "vitest";
import type { RegimenFormValues } from "../../../api/regimenTypes";
import { newRowId } from "./rowIds";

const ROW_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const CLAUDE_ROW = /^(drug|effect|question)[0-9]+$/;

function form(drugIds: string[]): RegimenFormValues {
  return {
    basic: { display_name: null, code: null, target: null, cycle_days: null },
    drugs: drugIds.map((row_id) => ({
      row_id,
      name: null,
      route: null,
      days: [],
      times_per_day: null,
      start_note: null,
    })),
    side_effects: [],
    questions: [],
    notes: "",
  };
}

describe("newRowId", () => {
  it("節ごとの頭に a から順に振り、使っている id を避ける", () => {
    expect(newRowId(form([]), "drugs")).toBe("drug-add-a");
    expect(newRowId(form(["drug-add-a", "drug1"]), "drugs")).toBe("drug-add-b");
    expect(newRowId(form([]), "side_effects")).toBe("effect-add-a");
    expect(newRowId(form([]), "questions")).toBe("question-add-a");
  });

  it("row_id の書式に合い、Claude の行の形・数字3桁以上の終わりにならない", () => {
    const ids: string[] = [];
    for (let i = 0; i < 800; i += 1) {
      ids.push(newRowId(form(ids), "drugs"));
    }
    expect(new Set(ids).size).toBe(800);
    for (const id of ids) {
      expect(id).toMatch(ROW_ID_PATTERN);
      expect(id).not.toMatch(CLAUDE_ROW);
      expect(id).not.toMatch(/[0-9]{3,}$/);
    }
  });
});
