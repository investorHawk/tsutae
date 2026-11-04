/**
 * 医師 API: D4 レジメンの下書き・確認・採用（docs/architecture.md §8・9c）。
 * 2xx の本文は regimenGuards で検査する（契約と違えば invalid_response）。
 * 422 の issues（欄の id と理由）は `fieldIssuesOf(err)` で取り出す。
 */
import { ApiError, getJson, patchJson, postJson, seg } from "./http";
import {
  isAdoptRegimenResponse,
  isCreateRegimenDraftResponse,
  isFieldIssue,
  isRegimenDraftResponse,
  isRegimenDraftsResponse,
  isRegimenPreviewResponse,
  isRegimenTurnResponse,
} from "./regimenGuards";
import type {
  AdoptRegimenRequest,
  AdoptRegimenResponse,
  CreateRegimenDraftRequest,
  CreateRegimenDraftResponse,
  FieldIssue,
  PatchRegimenFieldsRequest,
  RegimenDraftResponse,
  RegimenDraftsResponse,
  RegimenPreview,
  RegimenTurnResponse,
} from "./regimenTypes";
import type { OkResponse } from "./types";
import { checked, isRecord } from "./validate";

/** 医師 API の打ち切り（ms。doctor.ts の DOCTOR_TIMEOUT_MS と同じ）。 */
const TIMEOUT_MS = 30_000;
/**
 * Claude の1往復の打ち切り（ms）。サーバーの上限（regimen_turn_timeout_s、既定 90 秒）を
 * 待ってから失敗の行つきの下書きが返るので、それより長くする。
 */
export const TURN_TIMEOUT_MS = 100_000;
const BASE = "/api/doctor/regimen-drafts";

const draftPath = (id: number): string => `${BASE}/${seg(id)}`;

/** 新しい下書き（{from: "new"}）か、既存のレジメンの版 N+1 の下書き（{skill}）。 */
export async function createRegimenDraft(
  body: CreateRegimenDraftRequest,
): Promise<CreateRegimenDraftResponse> {
  return checked<CreateRegimenDraftResponse>(
    await postJson<unknown>(BASE, body, { timeoutMs: TIMEOUT_MS }),
    isCreateRegimenDraftResponse,
  );
}

export async function listRegimenDrafts(): Promise<RegimenDraftsResponse> {
  return checked<RegimenDraftsResponse>(
    await getJson<unknown>(BASE, { timeoutMs: TIMEOUT_MS }),
    isRegimenDraftsResponse,
  );
}

export async function getRegimenDraft(
  id: number,
): Promise<RegimenDraftResponse> {
  return checked<RegimenDraftResponse>(
    await getJson<unknown>(draftPath(id), { timeoutMs: TIMEOUT_MS }),
    isRegimenDraftResponse,
  );
}

/**
 * 欄の直接編集・行の追加と削除。検査に掛かれば 422 invalid_fields（`fieldIssuesOf`）、
 * Claude の応答中は 409 working、読んでから書くまでに別の書き手が変えたら 409 conflict
 * （読み直す）。
 */
export async function patchRegimenFields(
  id: number,
  body: PatchRegimenFieldsRequest,
): Promise<RegimenDraftResponse> {
  return checked<RegimenDraftResponse>(
    await patchJson<unknown>(`${draftPath(id)}/fields`, body, {
      timeoutMs: TIMEOUT_MS,
    }),
    isRegimenDraftResponse,
  );
}

/**
 * Claude の1往復（先生の文を送り、応答まで待つ）。応答は往復の後の下書きと turn_error
 * （成功は null。時間切れ・失敗でも下書きは open に戻り、会話に失敗の行がある）。
 * 入力の文・依頼文に個人を特定しうる表現の疑いがあれば 422 h1_blocked（何も保存しない。
 * `fieldIssuesOf(err)` は掛かった場所 field_id "text"＝先生の文 / "prompt"＝依頼文の他の
 * 部分と、規則の名前の入った message。文面は返らない）、応答中・閉じた下書きは 409
 * working・not_open、読んでから始めるまでに直接編集が入れば 409 conflict（読み直す）。
 */
export async function postRegimenTurn(
  id: number,
  text: string,
): Promise<RegimenTurnResponse> {
  return checked<RegimenTurnResponse>(
    await postJson<unknown>(
      `${draftPath(id)}/turns`,
      { text },
      {
        timeoutMs: TURN_TIMEOUT_MS,
      },
    ),
    isRegimenTurnResponse,
  );
}

export async function discardRegimenDraft(id: number): Promise<OkResponse> {
  return checked<OkResponse>(
    await postJson<unknown>(`${draftPath(id)}/discard`, undefined, {
      timeoutMs: TIMEOUT_MS,
    }),
    (v) => v.ok === true,
  );
}

export async function previewRegimenDraft(id: number): Promise<RegimenPreview> {
  return checked<RegimenPreview>(
    await getJson<unknown>(`${draftPath(id)}/preview`, {
      timeoutMs: TIMEOUT_MS,
    }),
    isRegimenPreviewResponse,
  );
}

/**
 * 採用。確認の画面の後に値が変わっていれば 409 token_mismatch、確かめが無ければ
 * 409 ai_values_unconfirmed。stale・schedule_locked・code_taken も 409。
 */
export async function adoptRegimenDraft(
  id: number,
  body: AdoptRegimenRequest,
): Promise<AdoptRegimenResponse> {
  return checked<AdoptRegimenResponse>(
    await postJson<unknown>(`${draftPath(id)}/adopt`, body, {
      timeoutMs: TIMEOUT_MS,
    }),
    isAdoptRegimenResponse,
  );
}

/** 失敗の本文の issues（欄の id と理由）。形が違えば空。 */
export function fieldIssuesOf(err: unknown): FieldIssue[] {
  if (!(err instanceof ApiError) || !isRecord(err.body)) {
    return [];
  }
  const issues = err.body.issues;
  if (!Array.isArray(issues)) {
    return [];
  }
  return issues.filter((i): i is FieldIssue => isRecord(i) && isFieldIssue(i));
}
