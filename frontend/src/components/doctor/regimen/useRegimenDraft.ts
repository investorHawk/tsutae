import { useCallback, useEffect, useRef, useState } from "react";
import {
  createRegimenDraft,
  discardRegimenDraft,
  fieldIssuesOf,
  getRegimenDraft,
  patchRegimenFields,
  postRegimenTurn,
} from "../../../api/regimenDrafts";
import type {
  CreateRegimenDraftRequest,
  FieldIssue,
  PatchRegimenFieldsRequest,
  RegimenDraft,
} from "../../../api/regimenTypes";

/** 欄の id → 理由（422 の issues。message に入力の文面は入らない）。 */
export type FieldErrors = Readonly<Record<string, readonly string[]>>;

export interface RegimenDraftApi {
  draft: RegimenDraft | null;
  /** 下書きを開いている・読み直している */
  loading: boolean;
  /** この画面から送った Claude の1往復の最中 */
  busy: boolean;
  /**
   * 応答中（この画面の往復か、サーバーの下書きが working）。左の欄・下のバー・確認の
   * 画面を止める。working のときは少し待って読み直す。
   */
  working: boolean;
  /** 直前の失敗の code（無ければ null） */
  error: string | null;
  /** 往復の結果を捨てた等の知らせ（失敗ではない） */
  notice: string | null;
  fieldErrors: FieldErrors;
  /** 送る文が H1 に掛かった（掛かった場所と規則の名前。文面は返らない） */
  blocked: readonly FieldIssue[] | null;
  open: (req: CreateRegimenDraftRequest) => Promise<RegimenDraft | null>;
  load: (id: number) => Promise<void>;
  /** 直接編集。fieldIds は今回の欄（成功したら欄の下の理由を消す）。 */
  patch: (
    body: PatchRegimenFieldsRequest,
    fieldIds?: readonly string[],
  ) => Promise<boolean>;
  /** Claude に送る。true なら入力欄を空にしてよい（先生の文が会話に入った） */
  sendTurn: (text: string) => Promise<boolean>;
  discard: () => Promise<boolean>;
  /** 送り待ちの直接編集が全て終わるまで待つ（確認へ進む前など） */
  settle: () => Promise<void>;
  close: () => void;
  setFieldError: (fieldId: string, message: string | null) => void;
}

/** サーバーの下書きが working のとき、読み直すまでの間（ms）。 */
export const WORKING_RELOAD_MS = 2000;

const RELOAD_CODES = new Set([
  "conflict",
  "working",
  "not_open",
  "unknown_row",
]);

function withoutIds(errors: FieldErrors, ids: readonly string[]): FieldErrors {
  const next = { ...errors };
  for (const id of ids) {
    delete next[id];
  }
  return next;
}

function issuesToErrors(
  errors: FieldErrors,
  issues: readonly FieldIssue[],
): FieldErrors {
  const next: Record<string, readonly string[]> = { ...errors };
  for (const issue of issues) {
    next[issue.field_id] = [...(next[issue.field_id] ?? []), issue.message];
  }
  return next;
}

/**
 * D4 レジメンの下書き1つ（開く・直接編集・Claude の1往復・捨てる）。直接編集は順に
 * 送り（読んでから書くまでの衝突 409 conflict を避ける）、往復は直前の編集を待ってから送る。
 * 409 conflict・working などは下書きを読み直す。
 */
export function useRegimenDraft(
  handleError: (err: unknown) => string,
): RegimenDraftApi {
  const [draft, setDraft] = useState<RegimenDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [blocked, setBlocked] = useState<readonly FieldIssue[] | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const idRef = useRef<number | null>(null);

  const show = useCallback((next: RegimenDraft | null) => {
    idRef.current = next?.id ?? null;
    setDraft(next);
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setNotice(null);
    setFieldErrors({});
    setBlocked(null);
  }, []);

  const reload = useCallback(async () => {
    const id = idRef.current;
    if (id === null) {
      return;
    }
    try {
      show((await getRegimenDraft(id)).draft);
    } catch (err) {
      setError(handleError(err));
    }
  }, [handleError, show]);

  const open = useCallback(
    async (req: CreateRegimenDraftRequest) => {
      reset();
      setLoading(true);
      try {
        const res = await createRegimenDraft(req);
        show(res.draft);
        return res.draft;
      } catch (err) {
        setError(handleError(err));
        return null;
      } finally {
        setLoading(false);
      }
    },
    [handleError, reset, show],
  );

  const load = useCallback(
    async (id: number) => {
      reset();
      setLoading(true);
      idRef.current = id;
      await reload();
      setLoading(false);
    },
    [reload, reset],
  );

  const runPatch = useCallback(
    async (body: PatchRegimenFieldsRequest, fieldIds: readonly string[]) => {
      const id = idRef.current;
      if (id === null) {
        return false;
      }
      try {
        const res = await patchRegimenFields(id, body);
        show(res.draft);
        setFieldErrors((prev) => withoutIds(prev, fieldIds));
        setError(null);
        return true;
      } catch (err) {
        const issues = fieldIssuesOf(err);
        if (issues.length > 0) {
          setFieldErrors((prev) =>
            issuesToErrors(withoutIds(prev, fieldIds), issues),
          );
          return false;
        }
        // 理由の無い失敗（h1_blocked など）でも、今回の欄の前の理由は消す
        setFieldErrors((prev) => withoutIds(prev, fieldIds));
        const code = handleError(err);
        setError(code);
        if (RELOAD_CODES.has(code)) {
          await reload();
        }
        return false;
      }
    },
    [handleError, reload, show],
  );

  const patch = useCallback(
    (body: PatchRegimenFieldsRequest, fieldIds: readonly string[] = []) => {
      const next = queue.current.then(() => runPatch(body, fieldIds));
      queue.current = next.catch(() => undefined);
      return next;
    },
    [runPatch],
  );

  const sendTurn = useCallback(
    async (text: string) => {
      const id = idRef.current;
      if (id === null) {
        return false;
      }
      setBusy(true);
      setError(null);
      setNotice(null);
      setBlocked(null);
      try {
        await queue.current;
        const res = await postRegimenTurn(id, text);
        show(res.draft);
        // 先生の文が会話に入ったか（失敗の往復も文と失敗の行が入る。捨てた往復は入らない）
        const sent = res.draft.chat.some(
          (row) =>
            row.role === "doctor" &&
            row.generation === res.draft.generation &&
            row.text === text,
        );
        if (res.turn_error === "discarded" || !sent) {
          setNotice(
            "この往復の結果は反映しませんでした（古い往復の結果でした）。下書きを読み直しました。送った文は入力欄に残しています",
          );
          await reload();
          return false;
        }
        return true;
      } catch (err) {
        const code = handleError(err);
        if (code === "h1_blocked") {
          setBlocked(fieldIssuesOf(err));
          return false;
        }
        setError(code);
        await reload();
        return false;
      } finally {
        setBusy(false);
      }
    },
    [handleError, reload, show],
  );

  const settle = useCallback(() => queue.current.then(() => undefined), []);

  // ほかの画面・前の読み込みで往復の最中だった下書きは、終わるまで少しずつ読み直す
  const serverWorking = draft?.status === "working";
  useEffect(() => {
    if (!serverWorking || busy) {
      return;
    }
    const timer = window.setTimeout(() => void reload(), WORKING_RELOAD_MS);
    return () => window.clearTimeout(timer);
  }, [draft, serverWorking, busy, reload]);

  const discard = useCallback(async () => {
    const id = idRef.current;
    if (id === null) {
      return false;
    }
    await queue.current;
    try {
      await discardRegimenDraft(id);
      show(null);
      reset();
      return true;
    } catch (err) {
      setError(handleError(err));
      return false;
    }
  }, [handleError, reset, show]);

  const close = useCallback(() => {
    show(null);
    reset();
  }, [reset, show]);

  const setFieldError = useCallback(
    (fieldId: string, message: string | null) => {
      setFieldErrors((prev) =>
        message === null
          ? withoutIds(prev, [fieldId])
          : { ...prev, [fieldId]: [message] },
      );
    },
    [],
  );

  return {
    draft,
    loading,
    busy,
    working: busy || serverWorking,
    error,
    notice,
    fieldErrors,
    blocked,
    open,
    load,
    patch,
    sendTurn,
    discard,
    settle,
    close,
    setFieldError,
  };
}
