import { describe, expect, it } from "vitest";
import { notesLayout } from "../src/lib/pipelineNotes";
import { SDK_FRAME } from "../src/scenes/pipelineLayout";
import { SUBTITLE_TOP } from "../src/theme";

/** 図の上端（SDK の枠のラベルの上）と下端（SDK の枠の下） */
const DIAGRAM_TOP = SDK_FRAME.y - 22;
const DIAGRAM_BOTTOM = SDK_FRAME.y + SDK_FRAME.h;

describe("notesLayout（pipeline の注記の置き場所）", () => {
  it("注記が無ければ図は縮めない（案 A・C は今のまま）", () => {
    expect(notesLayout(0)).toMatchObject({ scale: 1, tops: [] });
  });

  it("1 行なら図は縮めずに、図の下・字幕の帯の上に収まる", () => {
    const l = notesLayout(1);
    expect(l.scale).toBe(1);
    expect(l.tops[0]).toBeGreaterThan(DIAGRAM_BOTTOM);
    expect(l.tops[0] + l.height).toBeLessThan(SUBTITLE_TOP);
  });

  it("2 行なら図を上端を軸に縮め、注記どうし・図・字幕の帯に重ならない", () => {
    const l = notesLayout(2);
    expect(l.scale).toBeLessThan(1);
    expect(l.scale).toBeGreaterThan(0.85);
    const scaledBottom = DIAGRAM_TOP + (DIAGRAM_BOTTOM - DIAGRAM_TOP) * l.scale;
    expect(l.tops[0]).toBeGreaterThan(scaledBottom);
    expect(l.tops[1]).toBeGreaterThanOrEqual(l.tops[0] + l.height);
    expect(l.tops[1] + l.height).toBeLessThan(SUBTITLE_TOP);
    expect(l.origin).toEqual({ x: 960, y: DIAGRAM_TOP });
  });
});
