/**
 * D4 レジメン: 確認の画面の「AI が入れた値」。一覧は標準の値だけを行ごとに1行で出し、
 * 「削除」は行ごと消すか標準の値の欄だけを空にする。smoke と同じ形（regimenTestingDemo）。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RegimenDraft, RegimenPreview } from "../../../api/regimenTypes";
import { fixtureBody } from "../../../test/apiFixtures";
import { jsonResponse } from "../../../test/fetchMock";
import {
  bodiesOf,
  countOf,
  mockApi,
  renderRoute,
  type RouteValue,
} from "../testing";
import RegimenSettings from "./RegimenSettings";
import {
  DRAFTS,
  REGIMENS,
  fieldsKey,
  getKey,
  previewKey,
  regimensBody,
} from "./regimenTesting";
import { demoDraft, demoPreview } from "./regimenTestingDemo";

afterEach(() => {
  vi.unstubAllGlobals();
});

function api(
  draft: RegimenDraft,
  extra: Record<string, RouteValue> = {},
): ReturnType<typeof mockApi> {
  return mockApi({
    [REGIMENS]: regimensBody(),
    [DRAFTS]: fixtureBody("doctor_regimen_drafts") as object,
    [getKey(1)]: { draft },
    [previewKey(1)]: demoPreview(),
    ...extra,
  });
}

async function openConfirm() {
  renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
  await userEvent.click(
    await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き/ }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "確認へ進む" }),
  );
  await screen.findByRole("heading", { name: /AI が入れた値/ });
}

function withoutRow(preview: RegimenPreview, rowKey: string): RegimenPreview {
  return {
    ...preview,
    ai_values: preview.ai_values.filter(
      (v) => !v.field_id.startsWith(`${rowKey}.`),
    ),
  };
}

describe("D4 レジメン: 確認の画面の一覧", () => {
  it("FOLFIRI＋BV は 12 行（質問5・副作用7）。列は欄・値・操作で、出どころの列は無い", async () => {
    api(demoDraft());
    await openConfirm();
    expect(
      screen.getByRole("heading", {
        name: "AI が入れた値（12 件）。先生の文に無かったので、標準の値から入れました（要らない行は削除できます）",
      }),
    ).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((c) => c.textContent),
    ).toEqual(["欄", "値", "操作"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(12);
    expect(within(table).queryByText("標準の値")).toBeNull();
    // 先生の文からの欄（基本・薬）は出ない
    expect(within(table).queryByText(/ベバシズマブ/)).toBeNull();
    expect(within(table).queryByText(/FOLFIRI-BV/)).toBeNull();
    expect(within(rows[0]).getByText("副作用 · 下痢")).toBeInTheDocument();
    expect(
      within(rows[0]).getByText(
        "患者の言い方: 下痢、お腹がゆるい／CTCAE の用語: 下痢／対応する質問: 下痢",
      ),
    ).toBeInTheDocument();
    // 同じ名前の副作用と質問をボタンの名前でも見分ける
    expect(
      screen.getByRole("button", { name: "副作用 · 下痢 の値を削除" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "質問 · 下痢 の値を削除" }),
    ).toBeInTheDocument();
  });

  it("フォームの下のバーも同じ数え方（12 行）", async () => {
    api(demoDraft());
    renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
    await userEvent.click(
      await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き/ }),
    );
    expect(
      await screen.findByText(
        "そろいました。AI が入れた 12 行は確認の画面でも一覧にします",
      ),
    ).toBeInTheDocument();
  });
});

describe("D4 レジメン: 一覧の削除", () => {
  it("全て標準の値の副作用の行は行ごと消し、確認を取り直して印を外す", async () => {
    const previews = [
      demoPreview(),
      withoutRow(demoPreview(), "side_effects.effect7"),
    ];
    const fetchMock = api(demoDraft(), {
      [fieldsKey(1)]: { draft: demoDraft() },
      [previewKey(1)]: () => jsonResponse(previews.shift()),
    });
    await openConfirm();
    const check = screen.getByLabelText("上の値を全て確かめました");
    await userEvent.click(check);
    expect(check).toBeChecked();
    await userEvent.click(
      screen.getByRole("button", { name: "副作用 · 髪が抜ける の値を削除" }),
    );
    expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([
      { deletes: ["side_effects.effect7"] },
    ]);
    expect(
      await screen.findByRole("heading", { name: /AI が入れた値（11 件）/ }),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, previewKey(1))).toBe(2);
    expect(screen.getByLabelText("上の値を全て確かめました")).not.toBeChecked();
  });

  it("質問の行は、その key を指す副作用の question_key も同じ PATCH で空にする", async () => {
    const fetchMock = api(demoDraft(), {
      [fieldsKey(1)]: { draft: demoDraft() },
    });
    await openConfirm();
    await userEvent.click(
      screen.getByRole("button", { name: "質問 · 下痢 の値を削除" }),
    );
    expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([
      {
        deletes: ["questions.question1"],
        changes: [
          { field_id: "side_effects.effect1.question_key", value: null },
        ],
      },
    ]);
    await waitFor(() => expect(countOf(fetchMock, previewKey(1))).toBe(2));
  });

  it("先生の欄が混ざる行は、標準の値の欄だけを空にする", async () => {
    const draft = demoDraft();
    const mixed = {
      ...draft,
      sources: {
        ...draft.sources,
        "side_effects.effect7.phrases": "doctor_edit" as const,
      },
    };
    const fetchMock = api(mixed, { [fieldsKey(1)]: { draft: mixed } });
    await openConfirm();
    await userEvent.click(
      screen.getByRole("button", { name: "副作用 · 髪が抜ける の値を削除" }),
    );
    expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([
      {
        changes: [{ field_id: "side_effects.effect7.ctcae_terms", value: [] }],
      },
    ]);
  });

  it("サーバーが拒んだら（体温の質問など）案内を出し、確認は取り直さない", async () => {
    const fetchMock = api(demoDraft(), {
      [fieldsKey(1)]: () =>
        jsonResponse(
          {
            error: "invalid_form",
            issues: [
              {
                field_id: "questions",
                code: "temperature_required",
                message: "体温の質問は外せない",
              },
            ],
          },
          422,
        ),
    });
    await openConfirm();
    await userEvent.click(
      screen.getByRole("button", { name: "質問 · 下痢 の値を削除" }),
    );
    expect(
      await screen.findByText(/その値を削除できませんでした/),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, previewKey(1))).toBe(1);
  });

  it("必須が欠けたら（薬・症状の欠けなど）フォームへ戻る", async () => {
    const next = { ...demoPreview(), skill_md: null };
    const previews = [
      demoPreview(),
      {
        ...next,
        issues: [
          {
            field_id: "questions.question1.text",
            code: "required",
            message: "入力が要る",
          },
        ],
      },
    ];
    api(demoDraft(), {
      [fieldsKey(1)]: { draft: demoDraft() },
      [previewKey(1)]: () => jsonResponse(previews.shift()),
    });
    await openConfirm();
    await userEvent.click(
      screen.getByRole("button", { name: "質問 · 下痢 の値を削除" }),
    );
    expect(
      await screen.findByText(/必須の欄が空になったので、フォームに戻りました/),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "基本" })).toBeInTheDocument();
  });
});

describe("D4 レジメン: 凡例", () => {
  it("青枠は「先生の値」1行で、出どころによる保護の違いを文で分ける", async () => {
    api(demoDraft());
    renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
    await userEvent.click(
      await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き/ }),
    );
    const legend = await screen.findByLabelText("欄の状態");
    const doc = within(legend).getByText("先生の値").parentElement;
    expect(doc).toHaveTextContent(
      "先生の文から入った欄は次の文で Claude が直すことがある",
    );
    expect(doc).toHaveTextContent("直接入れた欄は頼まない限り書き換えない");
    expect(within(legend).queryByText("先生が入れた")).toBeNull();
    expect(within(legend).queryByText("先生の文から")).toBeNull();
    expect(legend.querySelectorAll(".rf-legend-tag--doc")).toHaveLength(1);
    expect(within(legend).getByText("AI が入れた")).toBeInTheDocument();
  });
});
