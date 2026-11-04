/**
 * 未処理の記載（D6）の記録ごとの伏せ字の状態（純関数。引数は書き換えない）。
 *
 * - 初めの状態: 保存済みの伏せ字があればそれ（「送る」）。無ければ疑われた区間（marks）を
 *   伏せた状態で「送らない」（医師が「送る（伏せて）」を選ぶまで何も変えない）
 * - 区間を変えたら、確かめた結果（check）と「確かめた」の印を捨てる（別の文になるため）
 * - 保存の本文は区間と印だけ（医師は文を書かない）
 */
import type {
  MaskCheckResponse,
  MaskSaveEntry,
  UnprocessedItem,
} from "../../api/types";
import { mergeSpans, sameSpans, type Span } from "./maskSpans";

export interface EntryMaskState {
  send: boolean;
  spans: Span[];
  /** 「個人を特定する語は無いことを確かめた」 */
  confirmed: boolean;
  /** 今の区間での「伏せ字を確かめる」の結果（区間を変えると null） */
  check: MaskCheckResponse | null;
}

export type MaskStates = Readonly<Record<number, EntryMaskState>>;

export function initialMaskState(item: UnprocessedItem): EntryMaskState {
  if (item.doctor_mask) {
    return {
      send: true,
      spans: mergeSpans(item.doctor_mask.spans),
      confirmed: item.doctor_mask.confirmed_clear,
      check: null,
    };
  }
  return {
    send: false,
    spans: mergeSpans(item.marks),
    confirmed: false,
    check: null,
  };
}

export function initialMaskStates(
  items: readonly UnprocessedItem[],
): MaskStates {
  return Object.fromEntries(
    items.map((item) => [item.entry_id, initialMaskState(item)]),
  );
}

export function withSpans(
  state: EntryMaskState,
  spans: Span[],
): EntryMaskState {
  if (sameSpans(state.spans, spans)) {
    return state;
  }
  return { ...state, spans, confirmed: false, check: null };
}

export function withSend(state: EntryMaskState, send: boolean): EntryMaskState {
  return { ...state, send };
}

export function withCheck(
  state: EntryMaskState,
  check: MaskCheckResponse,
): EntryMaskState {
  return { ...state, check, confirmed: check.confirmable && state.confirmed };
}

export function withConfirmed(
  state: EntryMaskState,
  confirmed: boolean,
): EntryMaskState {
  return { ...state, confirmed };
}

/** 保存の本文（記録の並びは画面の順）。 */
export function saveEntries(
  items: readonly UnprocessedItem[],
  states: MaskStates,
): MaskSaveEntry[] {
  return items.map((item) => {
    const state = states[item.entry_id] ?? initialMaskState(item);
    return {
      entry_id: item.entry_id,
      send: state.send,
      spans: state.send ? state.spans.map((s) => ({ ...s })) : [],
      confirmed_clear: state.send && state.confirmed,
    };
  });
}

/** 「送る（伏せて）」の記録の数。 */
export function sendCount(states: MaskStates): number {
  return Object.values(states).filter((s) => s.send).length;
}
