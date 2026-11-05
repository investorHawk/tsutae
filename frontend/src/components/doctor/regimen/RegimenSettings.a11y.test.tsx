/**
 * D4 レジメン: キーボードと読み上げ（画面が替わった・行が消えた後の focus、タブの中身の
 * 名前、部品集の小窓の閉じ方、AI が変えた欄の札の文字）。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RegimenDraft } from "../../../api/regimenTypes";
import { fixtureBody } from "../../../test/apiFixtures";
import { jsonResponse } from "../../../test/fetchMock";
import { mockApi, renderRoute, type RouteValue } from "../testing";
import RegimenSettings from "./RegimenSettings";
import {
  DRAFTS,
  LIBRARY,
  REGIMENS,
  draftOf,
  fieldsKey,
  getKey,
  previewKey,
  previewOf,
  regimensBody,
} from "./regimenTesting";

afterEach(() => {
  vi.unstubAllGlobals();
});

function base(): RegimenDraft {
  return draftOf("doctor_regimen_draft");
}

function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    [REGIMENS]: regimensBody(),
    [DRAFTS]: fixtureBody("doctor_regimen_drafts") as object,
    [getKey(1)]: { draft: base() },
    ...extra,
  });
}

async function openDraft() {
  renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
  await userEvent.click(
    await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き/ }),
  );
  await screen.findByRole("heading", { name: "FOLFIRI＋BV（下書き・新規）" });
}

describe("D4 レジメン: focus の行き先", () => {
  it("タブの中身はタブの名前で読める", async () => {
    api();
    await openDraft();
    expect(
      screen.getByRole("tabpanel", { name: /FOLFIRI＋BV/ }),
    ).toBeInTheDocument();
  });

  it("確認へ進むと確認の見出しへ、フォームに戻ると基本の見出しへ", async () => {
    api({ [previewKey(1)]: previewOf("doctor_regimen_draft_preview") });
    await openDraft();
    await userEvent.click(screen.getByRole("button", { name: "確認へ進む" }));
    const heading = await screen.findByRole("heading", {
      name: /AI が入れた値/,
    });
    await waitFor(() => expect(heading).toHaveFocus());
    await userEvent.click(
      screen.getByRole("button", { name: "フォームに戻る" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "基本" })).toHaveFocus(),
    );
  });

  it("行を消すと次の行の最初の欄へ", async () => {
    const draft = base();
    const without = {
      ...draft,
      form: {
        ...draft.form,
        questions: draft.form.questions.filter(
          (q) => q.row_id !== "q-diarrhea",
        ),
      },
    };
    api({ [fieldsKey(1)]: () => jsonResponse({ draft: without }) });
    await openDraft();
    const list = screen.getByRole("list", { name: "患者への質問" });
    const index = draft.form.questions.findIndex(
      (q) => q.row_id === "q-diarrhea",
    );
    const next = draft.form.questions[index + 1];
    if (!next) {
      throw new Error("次の質問が無い");
    }
    await userEvent.click(
      within(list).getByRole("button", { name: "質問「下痢」を消す" }),
    );
    await waitFor(() =>
      expect(document.activeElement).toBe(
        document.getElementById(`rf-questions.${next.row_id}.label`),
      ),
    );
  });
});

describe("D4 レジメン: 部品集の小窓の閉じ方", () => {
  it("focus が小窓の外にあっても Esc で閉じ、背景を押しても閉じる（どちらも開いたボタンへ戻す）", async () => {
    api({ [LIBRARY]: fixtureBody("doctor_question_library") as object });
    await openDraft();
    const opener = screen.getByRole("button", { name: "部品集から選ぶ" });
    await userEvent.click(opener);
    await screen.findByRole("dialog");
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.activeElement).toBe(document.body);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();

    await userEvent.click(opener);
    const dialog = await screen.findByRole("dialog");
    const overlay = dialog.parentElement;
    if (!overlay) {
      throw new Error("背景が無い");
    }
    await userEvent.click(overlay);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });
});
