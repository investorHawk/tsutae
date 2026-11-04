/**
 * 患者画面の定型文。GET /api/patient/strings（patient_strings.json）を一度だけ読み、
 * usePatientStrings().t(key) で引く。患者画面の文字列はここからだけ出す（spec 3.1, 12節）。
 *
 * 読み込みの失敗で画面を空白のままにしない: 失敗したら取り直し、それでも駄目なら、
 * 本文が不正（必要なキーが欠ける・文字列でない）なら、ビルドに同梱した同じ正本で描く。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getPatientStrings } from "../api/patient";
import type { PatientStrings } from "../api/types";
import { BUNDLED_STRINGS, REQUIRED_KEYS } from "./bundledStrings";

export interface PatientStringsValue {
  /** 定型文を返す。未知のキーは空文字（console.warn を出す）。 */
  t: (key: string) => string;
  /** そのキーの定型文があるか（任意の定型文の有無を、警告を出さずに見る）。 */
  has: (key: string) => boolean;
}

const PatientStringsContext = createContext<PatientStringsValue | null>(null);

/** 失敗した時に取り直すまでの待ち時間（ms）。要素の数だけ取り直す。 */
export const DEFAULT_RETRY_DELAYS_MS: readonly number[] = [1000, 3000];

/**
 * API の本文を検査し、文字列の値だけを取り出す。オブジェクトでない・必要なキー
 * （REQUIRED_KEYS）が欠ける・その値が空や文字列でなければ null。
 */
export function validatePatientStrings(data: unknown): PatientStrings | null {
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    return null;
  }
  const record = data as Record<string, unknown>;
  const complete = REQUIRED_KEYS.every((key) => {
    const value = record[key];
    return typeof value === "string" && value.length > 0;
  });
  if (!complete) {
    return null;
  }
  const entries = Object.entries(record).filter(
    (pair): pair is [string, string] => typeof pair[1] === "string",
  );
  return Object.freeze(Object.fromEntries(entries));
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 読めれば検証済みのサーバーの文、取り直しても失敗・本文が不正なら同梱の文。 */
async function loadStrings(
  retryDelaysMs: readonly number[],
  isActive: () => boolean,
): Promise<PatientStrings> {
  for (let attempt = 0; attempt <= retryDelaysMs.length; attempt += 1) {
    if (attempt > 0) {
      await wait(retryDelaysMs[attempt - 1] ?? 0);
    }
    if (!isActive()) {
      break;
    }
    let data: unknown;
    try {
      data = await getPatientStrings();
    } catch (err) {
      console.error("patient strings: request failed", err);
      continue;
    }
    const strings = validatePatientStrings(data);
    if (strings) {
      return strings;
    }
    console.error("patient strings: invalid response, using bundled strings");
    break;
  }
  return BUNDLED_STRINGS;
}

function useTranslator(strings: PatientStrings): PatientStringsValue {
  const warned = useRef(new Set<string>());
  const t = useCallback(
    (key: string): string => {
      if (Object.prototype.hasOwnProperty.call(strings, key)) {
        return strings[key] ?? "";
      }
      if (!warned.current.has(key)) {
        warned.current.add(key);
        console.warn(`patient string not found: ${key}`);
      }
      return "";
    },
    [strings],
  );
  const has = useCallback(
    (key: string): boolean =>
      Object.prototype.hasOwnProperty.call(strings, key) &&
      (strings[key] ?? "") !== "",
    [strings],
  );
  return useMemo(() => ({ t, has }), [t, has]);
}

/** 読み込み済みの定型文で包む（テストや Storybook 的な用途）。 */
export function StaticPatientStringsProvider({
  strings,
  children,
}: {
  strings: PatientStrings;
  children: ReactNode;
}) {
  const value = useTranslator(strings);
  return (
    <PatientStringsContext.Provider value={value}>
      {children}
    </PatientStringsContext.Provider>
  );
}

/** 定型文を読み込んでから children を描く。読み込み中（取り直し中を含む）は何も出さない。 */
export function PatientStringsProvider({
  children,
  retryDelaysMs = DEFAULT_RETRY_DELAYS_MS,
}: {
  children: ReactNode;
  retryDelaysMs?: readonly number[];
}) {
  const [strings, setStrings] = useState<PatientStrings | null>(null);
  const delaysRef = useRef(retryDelaysMs);

  useEffect(() => {
    let active = true;
    void loadStrings(delaysRef.current, () => active).then((loaded) => {
      if (active) {
        setStrings(loaded);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  if (!strings) {
    return null;
  }
  return (
    <StaticPatientStringsProvider strings={strings}>
      {children}
    </StaticPatientStringsProvider>
  );
}

export function usePatientStrings(): PatientStringsValue {
  const value = useContext(PatientStringsContext);
  if (!value) {
    throw new Error(
      "usePatientStrings must be used inside PatientStringsProvider",
    );
  }
  return value;
}
