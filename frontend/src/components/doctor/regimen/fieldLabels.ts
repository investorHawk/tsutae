/**
 * 欄の id → 画面の呼び名（純関数）。Claude の返答の「変えた欄」の札と、欄の要素の id に使う。
 * 欄の id は backend の field_ids の形（`basic.cycle_days`・`drugs.<row_id>.days`・`notes`）。
 */
import type { RegimenFormValues } from "../../../api/regimenTypes";

export const SECTION_TITLES: Readonly<Record<string, string>> = {
  basic: "基本",
  drugs: "投与スケジュール",
  side_effects: "副作用",
  questions: "患者への質問",
  notes: "補足の指示",
};

export const BASIC_LABELS: Readonly<Record<string, string>> = {
  display_name: "レジメン名",
  code: "識別名",
  target: "対象",
  cycle_days: "1コースの日数",
};

const ROW_HEADS: Readonly<Record<string, string>> = {
  drugs: "薬",
  side_effects: "副作用",
  questions: "質問",
};

/** 画面の欄の要素の id（getElementById で引く。欄の id の「.」はそのまま使える）。 */
export function domIdOf(fieldId: string): string {
  return `rf-${fieldId}`;
}

/** 節の見出しの要素の id。 */
export function sectionDomId(section: string): string {
  return `rf-sec-${section}`;
}

function rowName(
  form: RegimenFormValues,
  section: string,
  rowId: string,
): string | null {
  if (section === "drugs") {
    return form.drugs.find((r) => r.row_id === rowId)?.name ?? null;
  }
  if (section === "side_effects") {
    return (
      form.side_effects.find((r) => r.row_id === rowId)?.phrases[0] ?? null
    );
  }
  if (section === "questions") {
    return form.questions.find((r) => r.row_id === rowId)?.label ?? null;
  }
  return null;
}

/**
 * 札のまとまり（基本の欄は1つずつ、行は行ごと）の鍵と呼び名。
 * 例: 「基本 · 1コースの日数」「薬 · ベバシズマブ」「補足の指示」。
 */
export function changeGroupOf(
  form: RegimenFormValues,
  fieldId: string,
): { key: string; label: string } {
  const [section, second] = fieldId.split(".");
  if (section === "basic" && second) {
    return {
      key: fieldId,
      label: `基本 · ${BASIC_LABELS[second] ?? second}`,
    };
  }
  const head = ROW_HEADS[section];
  if (head && second) {
    const name = rowName(form, section, second);
    return {
      key: `${section}.${second}`,
      label: `${head} · ${name ?? "（消した行）"}`,
    };
  }
  return { key: fieldId, label: SECTION_TITLES[section] ?? fieldId };
}
