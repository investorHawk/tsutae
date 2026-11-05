/**
 * D4 レジメンの画面テスト用（本番コードからは import しない）。下書きは実際の API の応答
 * （fixture doctor_regimen_*）を写して、id・フォーム・会話を流れに合わせて書き換える。
 */
import type {
  AssistantChatRow,
  ChatRow,
  DrugRow,
  RegimenDraft,
  RegimenFormValues,
  RegimenPreview,
} from "../../../api/regimenTypes";
import type { RegimenChoice, RegimensResponse } from "../../../api/types";
import { fixtureBody } from "../../../test/apiFixtures";

export const API = "/api/doctor";
export const REGIMENS = `GET ${API}/regimens`;
export const DRAFTS = `GET ${API}/regimen-drafts`;
export const CREATE = `POST ${API}/regimen-drafts`;
export const LIBRARY = `GET ${API}/question-library`;
export const DRUG_NAMES = `GET ${API}/regimen-drug-names`;

export const draftPath = (id: number) => `${API}/regimen-drafts/${id}`;
export const turnKey = (id: number) => `POST ${draftPath(id)}/turns`;
export const fieldsKey = (id: number) => `PATCH ${draftPath(id)}/fields`;
export const previewKey = (id: number) => `GET ${draftPath(id)}/preview`;
export const adoptKey = (id: number) => `POST ${draftPath(id)}/adopt`;
export const discardKey = (id: number) => `POST ${draftPath(id)}/discard`;
export const getKey = (id: number) => `GET ${draftPath(id)}`;

/** fixture の下書き（深く写したもの）。 */
export function draftOf(name: string): RegimenDraft {
  return (fixtureBody(name) as { draft: RegimenDraft }).draft;
}

export function previewOf(name: string): RegimenPreview {
  return fixtureBody(name) as RegimenPreview;
}

export function regimensBody(extra: RegimenChoice[] = []): RegimensResponse {
  const body = fixtureBody("doctor_regimens") as RegimensResponse;
  return { regimens: [...body.regimens, ...extra] };
}

const AT = "2026-11-09T10:00:00.000000+09:00";

export function doctorRow(text: string, generation: number): ChatRow {
  return { role: "doctor", text, generation, at: AT };
}

export function assistantRow(
  text: string,
  generation: number,
  patch: Partial<AssistantChatRow> = {},
): AssistantChatRow {
  return {
    role: "assistant",
    text,
    changed: [],
    ask: null,
    proposed: [],
    reply_hidden: false,
    generation,
    at: AT,
    ...patch,
  };
}

function drug(
  row_id: string,
  name: string,
  route: DrugRow["route"],
  end = 1,
): DrugRow {
  return {
    row_id,
    name,
    route,
    days: [{ start: 1, end }],
    times_per_day: null,
    start_note: null,
  };
}

/** FOLFOX@1 のフォーム（backend/tsutae/skills/regimen_forms/folfox.json と同じ値）。 */
export function folfoxForm(): RegimenFormValues {
  const capox = draftOf("doctor_regimen_draft_create_existing").form;
  return {
    basic: {
      display_name: "FOLFOX",
      code: "FOLFOX",
      target: "大腸がん",
      cycle_days: 14,
    },
    drugs: [
      drug("d-oxaliplatin", "オキサリプラチン", "infusion"),
      drug("d-levofolinate", "レボホリナート", "infusion"),
      drug("d-fu-bolus", "フルオロウラシル（急速静注）", "infusion"),
      drug("d-fu-pump", "フルオロウラシル（46時間）", "pump", 3),
    ],
    side_effects: capox.side_effects.filter((s) => s.row_id !== "se-hand-foot"),
    questions: capox.questions.filter((q) => q.row_id !== "q-hand-foot"),
    notes: "",
  };
}

/** 既存の FOLFOX@1 から開いた版2の下書き（create_existing の CAPOX の応答を写す）。 */
export function folfoxDraft(): RegimenDraft {
  return {
    ...draftOf("doctor_regimen_draft_create_existing"),
    id: 4,
    regimen: "FOLFOX",
    skill_name: "regimen-folfox",
    display_name: "FOLFOX",
    form: folfoxForm(),
  };
}
