import { useCallback, useRef, useState } from "react";
import {
  adoptRegimenDraft,
  fieldIssuesOf,
  previewRegimenDraft,
} from "../../../api/regimenDrafts";
import type {
  AdoptRegimenResponse,
  FieldIssue,
  RegimenPreview,
} from "../../../api/regimenTypes";

/** 採用の 409 のうち、確認の画面を出し直せば進めるもの。 */
const REFRESH_CODES = new Set(["token_mismatch", "ai_values_unconfirmed"]);

export interface RegimenConfirmApi {
  preview: RegimenPreview | null;
  loading: boolean;
  /** 「上の値を全て確かめました」（確認の画面の版＝confirm_token に結びつく） */
  confirmed: boolean;
  setConfirmed: (value: boolean) => void;
  adopting: boolean;
  error: string | null;
  /** 422 invalid_form の理由 */
  issues: readonly FieldIssue[];
  load: () => Promise<RegimenPreview | null>;
  adopt: () => Promise<AdoptRegimenResponse | null>;
  clear: () => void;
}

/**
 * D4 レジメンの確認と採用。確認の画面を出すたびに confirm_token が変わるので、取り直したら
 * 確かめの印を外す（値が変わった後の確かめを使い回さない）。
 * 取りに行っている間に下書きが替わった・閉じた（clear）なら、返った確認は捨てる
 * （別の下書きの確認・token を今の下書きの画面に混ぜない）。
 */
export function useRegimenConfirm(
  draftId: number | null,
  handleError: (err: unknown) => string,
): RegimenConfirmApi {
  // 確認は取りに行った下書きの id と一緒に持ち、今の下書きと違えば無いものとして返す
  const [held, setHeld] = useState<{
    draftId: number;
    preview: RegimenPreview;
  } | null>(null);
  const preview =
    held !== null && held.draftId === draftId ? held.preview : null;
  const [loading, setLoading] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [adopting, setAdopting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issues, setIssues] = useState<readonly FieldIssue[]>([]);
  // 今の下書き（毎回の描画で書く）と、取りに行った回の番号（clear・次の取得で進む）
  const latestId = useRef(draftId);
  latestId.current = draftId;
  const seq = useRef(0);

  const fetchPreview = useCallback(async () => {
    if (draftId === null || draftId !== latestId.current) {
      return null;
    }
    const mine = ++seq.current;
    const current = () => mine === seq.current && draftId === latestId.current;
    setLoading(true);
    try {
      const next = await previewRegimenDraft(draftId);
      if (!current()) {
        return null;
      }
      setHeld({ draftId, preview: next });
      setConfirmed(false);
      return next;
    } catch (err) {
      const code = handleError(err);
      if (current()) {
        setError(code);
      }
      return null;
    } finally {
      if (mine === seq.current) {
        setLoading(false);
      }
    }
  }, [draftId, handleError]);

  const load = useCallback(async () => {
    setError(null);
    setIssues([]);
    return fetchPreview();
  }, [fetchPreview]);

  const adopt = useCallback(async () => {
    if (draftId === null || preview === null) {
      return null;
    }
    setAdopting(true);
    setError(null);
    setIssues([]);
    try {
      return await adoptRegimenDraft(draftId, {
        confirm_token: preview.confirm_token,
        ai_values_confirmed: confirmed,
      });
    } catch (err) {
      const code = handleError(err);
      setError(code);
      setIssues(fieldIssuesOf(err));
      if (REFRESH_CODES.has(code)) {
        await fetchPreview();
      }
      return null;
    } finally {
      setAdopting(false);
    }
  }, [confirmed, draftId, fetchPreview, handleError, preview]);

  const clear = useCallback(() => {
    seq.current += 1;
    setLoading(false);
    setHeld(null);
    setConfirmed(false);
    setError(null);
    setIssues([]);
  }, []);

  return {
    preview,
    loading,
    // 確かめの印も、今の下書きの確認に付いたものだけ
    confirmed: confirmed && preview !== null,
    setConfirmed,
    adopting,
    error,
    issues,
    load,
    adopt,
    clear,
  };
}
