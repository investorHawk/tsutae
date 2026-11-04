/**
 * D4 レジメンの API: 422 の issues の取り出しと、PATCH の送り方。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFixture } from "../test/apiFixtures";
import { callOf, jsonResponse, mockFetch } from "../test/fetchMock";
import { ApiError } from "./http";
import { fieldIssuesOf, patchRegimenFields } from "./regimenDrafts";

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
