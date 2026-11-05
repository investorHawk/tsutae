/**
 * D4 レジメンの API: 422 の issues の取り出しと、PATCH の送り方。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFixture } from "../test/apiFixtures";
import { callOf, jsonResponse, mockFetch } from "../test/fetchMock";
import { ApiError } from "./http";
import {
  TURN_TIMEOUT_MS,
  fieldIssuesOf,
  listRegimenDrugNames,
  patchRegimenFields,
  postRegimenTurn,
} from "./regimenDrafts";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fieldIssuesOf", () => {
  it("422 invalid_fields の issues（欄の id と理由）を返す", async () => {
    const fixture = apiFixture("doctor_regimen_draft_fields_invalid");
    mockFetch(() => jsonResponse(fixture.body, fixture.status));
    const err = await patchRegimenFields(1, { changes: [] }).catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("invalid_fields");
    expect(fieldIssuesOf(err)).toEqual([
      {
        field_id: "drugs.d-bv.name",
        code: "dose",
        message: "薬の量（数値＋mg 等）は持たない",
      },
    ]);
  });

  it("issues が無い・形が違う・ApiError でなければ空", () => {
    expect(
      fieldIssuesOf(new ApiError(409, "working", { error: "working" })),
    ).toEqual([]);
    expect(
      fieldIssuesOf(
        new ApiError(422, "invalid_fields", { issues: [{ field_id: 1 }, "x"] }),
      ),
    ).toEqual([]);
    expect(fieldIssuesOf(new Error("x"))).toEqual([]);
    expect(fieldIssuesOf(new ApiError(0, "network_error"))).toEqual([]);
  });
});

describe("patchRegimenFields", () => {
  it("PATCH で JSON を送る", async () => {
    const fixture = apiFixture("doctor_regimen_draft_fields_existing");
    const mock = mockFetch(() => jsonResponse(fixture.body, fixture.status));
    await patchRegimenFields(2, {
      changes: [{ field_id: "notes", value: "x" }],
    });
    const sent = callOf(mock);
    expect(sent.method).toBe("PATCH");
    expect(sent.url).toBe("/api/doctor/regimen-drafts/2/fields");
    expect(sent.body).toEqual({ changes: [{ field_id: "notes", value: "x" }] });
  });
});

describe("postRegimenTurn", () => {
  it("POST .../turns に {text} を送り、往復の後の下書きを返す", async () => {
    const fixture = apiFixture("doctor_regimen_draft_turn");
    const mock = mockFetch(() => jsonResponse(fixture.body, fixture.status));
    const res = await postRegimenTurn(3, "14日ごと");
    const sent = callOf(mock);
    expect(sent.method).toBe("POST");
    expect(sent.url).toBe("/api/doctor/regimen-drafts/3/turns");
    expect(sent.body).toEqual({ text: "14日ごと" });
    expect(res.turn_error).toBeNull();
    const last = res.draft.chat[res.draft.chat.length - 1];
    expect(last.role).toBe("assistant");
    if (last.role === "assistant") {
      expect(last.ask?.field_id).toBe("drugs.drug1.days");
      expect(last.changed).toContain("basic.cycle_days");
    }
  });

  it("打ち切りはサーバーの上限（90 秒）より長い", () => {
    expect(TURN_TIMEOUT_MS).toBeGreaterThan(90_000);
  });

  it("H1 に掛かれば ApiError(422, h1_blocked)", async () => {
    const fixture = apiFixture("doctor_regimen_draft_turn_h1");
    mockFetch(() => jsonResponse(fixture.body, fixture.status));
    const err = await postRegimenTurn(3, "x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    expect((err as ApiError).code).toBe("h1_blocked");
    // 掛かった場所（text = 先生の文、prompt = 依頼文の他の部分）と規則の名前だけ
    expect(fieldIssuesOf(err)).toEqual([
      {
        field_id: "text",
        code: "identifier",
        message: "個人を特定しうる表現の疑い（id_like）",
      },
    ]);
  });
});

describe("listRegimenDrugNames", () => {
  it("GET で名前の一覧を読む", async () => {
    const fixture = apiFixture("doctor_regimen_drug_names");
    const mock = mockFetch(() => jsonResponse(fixture.body));
    await expect(listRegimenDrugNames()).resolves.toEqual(fixture.body);
    expect(callOf(mock).method).toBe("GET");
    expect(callOf(mock).url).toBe("/api/doctor/regimen-drug-names");
  });

  it.each([[{}], [{ names: "パクリタキセル" }], [{ names: [1] }]])(
    "形が違えば invalid_response（%j）",
    async (body) => {
      mockFetch(() => jsonResponse(body));
      const err = await listRegimenDrugNames().catch((e: unknown) => e);
      expect((err as ApiError).code).toBe("invalid_response");
    },
  );
});
