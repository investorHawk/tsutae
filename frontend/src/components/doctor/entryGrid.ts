/**
 * 患者の画面（D2）の記録の経過表の、列と行を決める純関数（引数は書き換えない）。
 * - 列: 記録に出てくる question_key ごとに1列。既知の質問は経過表の順、知らない質問は
 *   最初に出てきた順で後ろ。質問集の版で質問が違っても、同じ key は同じ列に入る
 * - 行: 記録を新しい順に並べ、受診日（その日の最初の受付）の行を受付の時刻の位置に入れる。
 *   受付より後の記録は上、前の記録は下。受付と同じ時刻の記録は受付の前（下）とみなす
 *   （患者画面の受診日の区切りと同じ規則）
 */
import type {
  AnswerValue,
  DoctorEntry,
  IsoDate,
  IsoDateTime,
  PatientVisit,
} from "../../api/types";
import { QUESTION_ORDER, questionLabel } from "./answerLabels";

export interface GridColumn {
  key: string;
  label: string;
  /** level = なし・ある・つらい、temperature = 体温 */
  kind: "level" | "temperature";
}

export interface VisitDay {
  visit_date: IsoDate;
  /** その日の最初の受付の時刻 */
  received_at: IsoDateTime;
}

export type GridRow =
  | { kind: "entry"; entry: DoctorEntry }
  | { kind: "visit"; visit: VisitDay };

const TEMPERATURE_VALUES: readonly AnswerValue[] = ["measured", "not_measured"];

function msOf(value: string): number {
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? 0 : ms;
}

function rank(key: string, seen: readonly string[]): number {
  const known = QUESTION_ORDER.indexOf(key);
  return known >= 0 ? known : QUESTION_ORDER.length + seen.indexOf(key);
}

export function gridColumns(entries: readonly DoctorEntry[]): GridColumn[] {
  const seen: string[] = [];
  const temperature = new Set<string>();
  for (const entry of entries) {
    for (const answer of entry.answers) {
      if (!seen.includes(answer.question_key)) {
        seen.push(answer.question_key);
      }
      if (TEMPERATURE_VALUES.includes(answer.value)) {
        temperature.add(answer.question_key);
      }
    }
  }
  const ordered = [...seen].sort((a, b) => rank(a, seen) - rank(b, seen));
  const column = (key: string): GridColumn => ({
    key,
    label: questionLabel(key),
    kind: temperature.has(key) ? "temperature" : "level",
  });
  const levels = ordered.filter((k) => !temperature.has(k)).map(column);
  const temps = ordered.filter((k) => temperature.has(k)).map(column);
  return [...levels, ...temps];
}

/** 受診を受診日ごとに1件（その日の最初の受付）にして新しい順に。 */
export function visitDays(visits: readonly PatientVisit[]): VisitDay[] {
  const first = new Map<IsoDate, IsoDateTime>();
  for (const visit of visits) {
    const current = first.get(visit.visit_date);
    if (current === undefined || msOf(visit.created_at) < msOf(current)) {
      first.set(visit.visit_date, visit.created_at);
    }
  }
  return [...first.entries()]
    .map(([visit_date, received_at]) => ({ visit_date, received_at }))
    .sort((a, b) => msOf(b.received_at) - msOf(a.received_at));
}

function newestFirst(entries: readonly DoctorEntry[]): DoctorEntry[] {
  return [...entries].sort(
    (a, b) => msOf(b.recorded_at) - msOf(a.recorded_at) || b.id - a.id,
  );
}

/**
 * 記録と受診日の行（新しい順）。truncated（直近の記録だけを出している）なら、出した記録より
 * 前の受診日は出さない（その間の記録が見えないので、受診日だけが続いて並ぶのを避ける）。
 */
export function gridRows(
  entries: readonly DoctorEntry[],
  visits: readonly PatientVisit[],
  truncated: boolean,
): GridRow[] {
  const pending = visitDays(visits);
  const rows: GridRow[] = [];
  for (const entry of newestFirst(entries)) {
    const recorded = msOf(entry.recorded_at);
    while (pending.length > 0 && msOf(pending[0]!.received_at) >= recorded) {
      rows.push({ kind: "visit", visit: pending.shift()! });
    }
    rows.push({ kind: "entry", entry });
  }
  const rest = truncated && entries.length > 0 ? [] : pending;
  return [...rows, ...rest.map((visit) => ({ kind: "visit" as const, visit }))];
}
