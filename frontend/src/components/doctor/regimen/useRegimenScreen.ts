import { useCallback, useState } from "react";
import type { PatchRegimenFieldsRequest } from "../../../api/regimenTypes";
import { domIdOf, sectionDomId } from "./fieldLabels";
import { askKeyOf, openAsk, patchTouchesAsk } from "./fieldState";
import { emptyValueOf } from "./fieldValues";
import type { AdoptedRegimen } from "./RegimenDone";
import {
  NEW_TAB_KEY,
  draftTabKey,
  skillTabKey,
  type RegimenTab,
} from "./tabList";
import { useRegimenCatalog } from "./useRegimenCatalog";
import { useRegimenConfirm } from "./useRegimenConfirm";
import { useRegimenDraft } from "./useRegimenDraft";

export type RegimenView = "form" | "confirm" | "done";

/** 描き直しの後に、並べた id のうち最初にある要素へ focus（無ければ何もしない）。 */
function focusFirst(...ids: string[]): void {
  window.setTimeout(() => {
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) {
        el.focus();
        return;
      }
    }
  }, 0);
}

/** 札から欄へ（描き直しの後に、欄か節の見出しへスクロールして focus）。 */
function focusField(fieldId: string): void {
  window.setTimeout(() => {
    const section = fieldId.split(".")[0] ?? fieldId;
    const el =
      document.getElementById(domIdOf(fieldId)) ??
      document.getElementById(sectionDomId(section));
    el?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    el?.focus();
  }, 0);
}

/**
 * D4 レジメンの画面の状態（タブ・表示の段階・下書き・確認・採用）。
 * 既存のタブを開くと POST /regimen-drafts {skill}（開いた下書きがあればそれ）、
 * 「＋ 新しいレジメン」は新しい下書きを作る。採用・破棄の後はタブの元を読み直す。
 * Claude の ask は、赤枠の欄（行・節）を直接直せば答えたことにする（answered）。
 */
export function useRegimenScreen(handleError: (err: unknown) => string) {
  const catalog = useRegimenCatalog(handleError);
  const editor = useRegimenDraft(handleError);
  const confirm = useRegimenConfirm(editor.draft?.id ?? null, handleError);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<RegimenView>("form");
  const [adopted, setAdopted] = useState<AdoptedRegimen | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [answered, setAnswered] = useState<string | null>(null);
  const draft = editor.draft;
  const ask = draft ? openAsk(draft, answered) : null;

  /** 直接編集（成功して ask の欄に触れていたら、その ask は答えたことにする）。 */
  const patch = useCallback(
    async (body: PatchRegimenFieldsRequest, fieldIds?: readonly string[]) => {
      const touches = draft && patchTouchesAsk(ask, body);
      const key = draft ? askKeyOf(draft) : null;
      const ok = await editor.patch(body, fieldIds);
      if (ok && touches) {
        setAnswered(key);
      }
      return ok;
    },
    [ask, draft, editor],
  );

  const pick = useCallback(
    async (tab: RegimenTab) => {
      await editor.settle();
      setView("form");
      setAdopted(null);
      setNote(null);
      confirm.clear();
      if (tab.kind === "skill") {
        setSelected(tab.key);
        await editor.open({ skill: tab.skill });
        await catalog.reload();
      } else if (tab.kind === "draft") {
        setSelected(tab.key);
        await editor.load(tab.draftId);
      } else {
        setSelected(NEW_TAB_KEY);
        const opened = await editor.open({ from: "new" });
        if (opened) {
          setSelected(draftTabKey(opened.id));
          await catalog.reload();
        }
      }
    },
    [catalog, confirm, editor],
  );

  const jump = useCallback((fieldId: string) => {
    setView("form");
    focusField(fieldId);
  }, []);

  const goConfirm = useCallback(async () => {
    setNote(null);
    // 欄を離れた直後の PATCH を待ってから確認を作る（古い値の確認・印にしない）
    await editor.settle();
    // 取りに行っている間に下書きが替わったら、confirm.preview は null になる（useRegimenConfirm）
    if (await confirm.load()) {
      setView("confirm");
      focusFirst("rf-ai-h", "rf-skill-h");
    }
  }, [confirm, editor]);

  const backToForm = useCallback(() => {
    setView("form");
    focusFirst(sectionDomId("basic"));
  }, []);

  /** Claude に送る。確認の画面で送ったなら、終わった後に確認を取り直す（印も外れる）。 */
  const sendTurn = useCallback(
    async (text: string) => {
      const ok = await editor.sendTurn(text);
      if (view === "confirm") {
        await confirm.load();
      }
      return ok;
    },
    [confirm, editor, view],
  );

  const deleteValue = useCallback(
    async (fieldId: string) => {
      const ok = await editor.patch(
        { changes: [{ field_id: fieldId, value: emptyValueOf(fieldId) }] },
        [fieldId],
      );
      if (!ok) {
        setNote(
          "その値を削除できませんでした。フォームに戻って欄の下の理由を見てください",
        );
        return;
      }
      const next = await confirm.load();
      if (next && next.issues.length > 0) {
        setView("form");
        setNote(
          "必須の欄が空になったので、フォームに戻りました。入れてから確認へ進んでください",
        );
        focusFirst(sectionDomId("basic"));
        return;
      }
      focusFirst("rf-ai-h", "rf-skill-h");
    },
    [confirm, editor],
  );

  const discard = useCallback(async () => {
    if (await editor.discard()) {
      setSelected(null);
      setView("form");
      confirm.clear();
      setNote("下書きを捨てました");
      await catalog.reload();
    }
  }, [catalog, confirm, editor]);

  const adopt = useCallback(async () => {
    const current = editor.draft;
    const result = await confirm.adopt();
    if (!current || !result) {
      return;
    }
    setAdopted({
      result,
      displayName: current.form.basic.display_name ?? result.regimen,
      isNew: current.base_version === null,
      questionCount: confirm.preview?.patient_preview.length ?? 0,
      cycleDays: current.form.basic.cycle_days,
    });
    setView("done");
    setSelected(skillTabKey(result.skill_name));
    editor.close();
    confirm.clear();
    await catalog.reload();
    focusFirst("rf-done-h");
  }, [catalog, confirm, editor]);

  const backToList = useCallback(() => {
    setAdopted(null);
    setSelected(null);
    setView("form");
  }, []);

  return {
    catalog,
    editor,
    confirm,
    selected,
    view,
    adopted,
    note,
    ask,
    patch,
    pick,
    jump,
    goConfirm,
    sendTurn,
    deleteValue,
    discard,
    adopt,
    backToList,
    backToForm,
  };
}
