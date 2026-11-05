import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "../../test/fetchMock";
import PatientCreateForm from "./PatientCreateForm";
import { countOf, mockApi, renderRoute } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

const REGIMENS = "GET /api/doctor/regimens";
const LIST = {
  regimens: [
    {
      code: "FOLFOX",
      skill_name: "regimen-folfox",
      version: 1,
      display_name: "FOLFOX",
    },
    {
      code: "CAPOX",
      skill_name: "regimen-capox",
      version: 1,
      display_name: "CAPOX",
    },
    {
      code: "RAM-WPTX",
      skill_name: "regimen-ram-wptx",
      version: 2,
      display_name: "RAM＋wPTX",
    },
  ],
};

function renderForm(onCreate = vi.fn()) {
  renderRoute(
    "/doctor/patients",
    "/doctor/patients",
    <PatientCreateForm busy={false} onCreate={onCreate} onCancel={vi.fn()} />,
  );
  return onCreate;
}

describe("PatientCreateForm（レジメンの選択肢は API から。T95）", () => {
  it("GET regimens の一覧を表示名で並べ、識別名で送る", async () => {
    const fetchMock = mockApi({ [REGIMENS]: LIST });
    const onCreate = renderForm();
    const select = await screen.findByLabelText("レジメン");
    const options = within(select).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "FOLFOX",
      "CAPOX",
      "RAM＋wPTX",
    ]);
    expect(options.map((o) => (o as HTMLOptionElement).value)).toEqual([
      "FOLFOX",
      "CAPOX",
      "RAM-WPTX",
    ]);
    expect(select).toHaveValue("FOLFOX"); // 先頭が既定
    await userEvent.selectOptions(select, "RAM-WPTX");
    await userEvent.click(screen.getByRole("button", { name: "追加する" }));
    expect(onCreate).toHaveBeenCalledWith("RAM-WPTX");
    expect(countOf(fetchMock, REGIMENS)).toBe(1);
  });

  it("一覧を読むまでは追加できない", async () => {
    mockApi({ [REGIMENS]: LIST });
    renderForm();
    expect(screen.getByRole("button", { name: "追加する" })).toBeDisabled();
    await screen.findByRole("option", { name: "CAPOX" });
    expect(screen.getByRole("button", { name: "追加する" })).toBeEnabled();
  });

  it.each([
    ["regimens が無い", { ok: true }],
    [
      "識別名の書式が違う",
      { regimens: [{ ...LIST.regimens[0], code: "folfox" }] },
    ],
    [
      "Skill 名が識別名と合わない",
      { regimens: [{ ...LIST.regimens[0], skill_name: "regimen-capox" }] },
    ],
    ["表示名が空", { regimens: [{ ...LIST.regimens[0], display_name: " " }] }],
    ["識別名が重なる", { regimens: [LIST.regimens[0], LIST.regimens[0]] }],
  ])(
    "応答が契約と違えば（%s）invalid_response で追加できない",
    async (_l, body) => {
      const onCreate = vi.fn();
      mockApi({ [REGIMENS]: body });
      renderForm(onCreate);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.getByRole("button", { name: "追加する" })).toBeDisabled();
    },
  );

  it("一覧が取れなければ code を出す", async () => {
    mockApi({ [REGIMENS]: () => jsonResponse({ error: "boom" }, 500) });
    renderForm();
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(screen.getByRole("button", { name: "追加する" })).toBeDisabled();
  });

  it("置かれたレジメンが1つも無ければその旨を出し、追加できない", async () => {
    mockApi({ [REGIMENS]: { regimens: [] } });
    renderForm();
    expect(
      await screen.findByText("選べるレジメンがありません"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "追加する" })).toBeDisabled();
  });
});
