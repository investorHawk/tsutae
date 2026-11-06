/**
 * D4 レジメンのタブ（純関数）: 採用済みのレジメン（表示名 版N。開いた下書きがあれば
 * 「版 N+1 の下書き」）・開いている新規の下書き・「＋ 新しいレジメン」。
 * 新規の下書きの名前は、開いている下書きならフォームのレジメン名（往復・直接編集の後の値）、
 * ほかは一覧（GET /regimen-drafts）の名前。空なら「新しいレジメン」（regimenName.ts）。
 */
import type { RegimenDraftSummary } from "../../../api/regimenTypes";
import type { RegimenChoice } from "../../../api/types";
import { regimenNameOf } from "./regimenName";

export type RegimenTab =
  | { key: string; kind: "skill"; label: string; sub: string; skill: string }
  | { key: string; kind: "draft"; label: string; sub: string; draftId: number }
  | { key: string; kind: "new"; label: string; sub: string };

export const NEW_TAB_KEY = "new";

export const skillTabKey = (skill: string): string => `skill:${skill}`;
export const draftTabKey = (id: number): string => `draft:${id}`;

/** 開いている下書きのうち、タブの名前に使う値だけ（RegimenDraft を渡せる）。 */
export interface OpenDraftName {
  id: number;
  form: { basic: { display_name: string | null } };
}

function freshLabel(
  draft: RegimenDraftSummary,
  current: OpenDraftName | null,
): string {
  return regimenNameOf(
    current && current.id === draft.id
      ? current.form.basic.display_name
      : draft.display_name,
  );
}

export function regimenTabs(
  regimens: readonly RegimenChoice[],
  drafts: readonly RegimenDraftSummary[],
  current: OpenDraftName | null = null,
): RegimenTab[] {
  const skills: RegimenTab[] = regimens.map((r) => {
    const open = drafts.find(
      (d) => d.base_version !== null && d.skill_name === r.skill_name,
    );
    return {
      key: skillTabKey(r.skill_name),
      kind: "skill",
      label: r.display_name,
      sub: open ? `版 ${open.version} の下書き` : `版 ${r.version}`,
      skill: r.skill_name,
    };
  });
  const fresh: RegimenTab[] = drafts
    .filter((d) => d.base_version === null)
    .map((d) => ({
      key: draftTabKey(d.id),
      kind: "draft",
      label: freshLabel(d, current),
      sub: "下書き（新規）",
      draftId: d.id,
    }));
  return [
    ...skills,
    ...fresh,
    { key: NEW_TAB_KEY, kind: "new", label: "＋ 新しいレジメン", sub: "" },
  ];
}
