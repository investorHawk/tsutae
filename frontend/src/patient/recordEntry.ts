/**
 * 記録の順序（docs/plan-device-records.md §5.2・§5.4）。文面は持たない。
 * 印をサーバーに付け、その応答の時刻で端末に保存する（端末の時計は使わないので Day はずれない）。
 * サーバーへ送るのは印だけで、回答・体温・自由記載は送らない。
 */
import { addRecordMark, undoRecordMark } from "../api/patientDevice";
import type {
  ClosedAnswer,
  DeviceEntry,
  EntryCreate,
  EntryKind,
  QuestionsResponse,
  RecordMarkResponse,
} from "../api/types";
import {
  deleteDeviceEntry,
  deviceEntriesOn,
  saveDeviceEntry,
} from "./deviceStore";

/**
 * 記録の ID（小文字の UUID v4）。入力の開始時に作る。crypto.randomUUID は https でしか
 * 使えない（開発で iPhone から http で開く）ので、getRandomValues から作る。
 */
export function newClientEntryId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  );
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

/** 記録の種類（backend の schemas.py EntryCreate.kind と同じ）。 */
function kindOf(entry: EntryCreate): EntryKind {
  if (entry.too_sick === true) {
    return "too_sick";
  }
  const hasAnswers = (entry.answers ?? []).length > 0;
  if (hasAnswers && entry.free_text) {
    return "mixed";
  }
  return hasAnswers ? "answers" : "free_text";
}

function answerOf(answer: ClosedAnswer, questions: QuestionsResponse) {
  const question = questions.questions.find(
    (q) => q.key === answer.question_key,
  );
  return {
    question_key: answer.question_key,
    value: answer.value,
    temperature: answer.temperature ?? null,
    question_text: question?.text ?? null,
  };
}

/** 入力と印の応答から、端末に置く1件を作る（質問の文の写しを持たせる）。 */
export function toDeviceEntry(
  pid: string,
  clientEntryId: string,
  entry: EntryCreate,
  questions: QuestionsResponse,
  mark: RecordMarkResponse,
): DeviceEntry {
  return {
    pid,
    client_entry_id: clientEntryId,
    recorded_at: mark.recorded_at,
    record_date: mark.record_date,
    kind: kindOf(entry),
    by_proxy: entry.by_proxy === true,
    skill_version: questions.skill_version,
    answers: (entry.answers ?? []).map((a) => answerOf(a, questions)),
    free_text: entry.free_text ?? null,
  };
}

/**
 * 印を付けて端末に保存する。どちらの失敗も例外で返す（呼ぶ側は入力を残し、同じ ID で押し直せる）。
 * 保存だけが失敗すると印が残るが、紙に「届いていない」と出るので事実と違う表示にはならない。
 */
export async function recordEntry(
  pid: string,
  clientEntryId: string,
  entry: EntryCreate,
  questions: QuestionsResponse,
): Promise<DeviceEntry> {
  const mark = await addRecordMark(pid);
  const saved = toDeviceEntry(pid, clientEntryId, entry, questions, mark);
  await saveDeviceEntry(saved);
  return saved;
}

/**
 * 記録の取り消し。サーバーが通したら端末の記録を消す。その日に端末の記録が他に無ければ
 * 印も消してもらう。端末の記録を消せなければ例外で返す（取り消しは何度送ってもよいので押し直せる）。
 */
export async function undoRecord(entry: DeviceEntry): Promise<void> {
  const sameDay = await deviceEntriesOn(entry.pid, entry.record_date);
  const others = sameDay.some(
    (e) => e.client_entry_id !== entry.client_entry_id,
  );
  await undoRecordMark(entry.pid, {
    recorded_at: entry.recorded_at,
    clear_mark: !others,
  });
  await deleteDeviceEntry(entry.pid, entry.client_entry_id);
}
