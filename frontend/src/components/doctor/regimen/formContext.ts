import { createContext, useContext } from "react";
import type {
  ChatAsk,
  PatchRegimenFieldsRequest,
  RegimenDraft,
} from "../../../api/regimenTypes";
import type { FieldErrors } from "./useRegimenDraft";

/** 左のフォームの欄が共通に使うもの（下書き・ask・応答中・保存）。 */
export interface RegimenFormContextValue {
  draft: RegimenDraft;
  ask: ChatAsk | null;
  /** Claude の応答中（全ての欄・行の操作を止める） */
  locked: boolean;
  fieldErrors: FieldErrors;
  /** 薬の名前の候補（読めなければ空） */
  drugNames: readonly string[];
  commit: (fieldId: string, value: unknown) => Promise<boolean>;
  patch: (
    body: PatchRegimenFieldsRequest,
    fieldIds?: readonly string[],
  ) => Promise<boolean>;
  setFieldError: (fieldId: string, message: string | null) => void;
}

export const RegimenFormContext = createContext<RegimenFormContextValue | null>(
  null,
);

export function useRegimenForm(): RegimenFormContextValue {
  const value = useContext(RegimenFormContext);
  if (!value) {
    throw new Error("RegimenFormContext の外で使った");
  }
  return value;
}
