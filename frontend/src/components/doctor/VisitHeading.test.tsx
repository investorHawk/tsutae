import { describe, expect, it } from "vitest";
import { visitHeaderStub } from "../../test/doctorStubs";
import { visitHeadingText } from "./VisitHeading";

describe("visitHeadingText", () => {
  it("受付番号・仮名ID・受付の日時（内部の番号は出さない）", () => {
    expect(visitHeadingText(visitHeaderStub())).toBe(
      "A-023 ・ P-DEMO0001 ・ 11月9日（月）18:16 受付",
    );
  });

  it("受付番号が消えていれば（印刷済み・期限切れ）受付番号を出さない", () => {
    expect(
      visitHeadingText(
        visitHeaderStub({ reception_no: null, status: "printed" }),
      ),
    ).toBe("P-DEMO0001 ・ 11月9日（月）18:16 受付");
  });
});
