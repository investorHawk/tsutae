import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { getQuestions } from "../../api/patient";
import type { EntryCreate, Question } from "../../api/types";
import { noticesFor } from "../../patient/fixedRules";
import { newClientEntryId, recordEntry } from "../../patient/recordEntry";
import { reloadPage } from "../../patient/reload";
import { usePatientStrings } from "../../strings/PatientStrings";
import {
  EMPTY_FORM,
  buildEntry,
  hasInput,
  temperatureErrors,
  unansweredCount,
  type EntryFormState,
  type TemperatureProblem,
} from "./entryForm";
import FreeTextField from "./FreeTextField";
import { LoadFailed, Loading } from "./LoadStatus";
import { DoneMessage, ErrorMessage } from "./Messages";
import NotRegistered from "./NotRegistered";
import { GENERIC_ERROR_KEY, isNotRegistered } from "./patientApi";
import ProxyToggle from "./ProxyToggle";
import QuestionList from "./QuestionList";
import TodayDone, { type SavedRecord } from "./TodayDone";
import TooSickButton, { SendingMessage } from "./TooSickButton";
import { useAsync } from "./useAsync";
import { useTooSickConfirm } from "./useTooSickConfirm";

/** どちらのボタンから送ったか（送信中・失敗の知らせをそのボタンの近くに出す）。 */
type Origin = "too_sick" | "submit";

type Phase =
  | { name: "editing" }
  | { name: "sending"; from: Origin }
  | { name: "done"; saved: SavedRecord }
  | { name: "not_registered" };

/** 「取り消しました」（取り消して記録する前の画面に戻った） */
const UNDONE_KEY = "today.undone";

/** 送るときに未登録と分かり、番号を入れて続きに戻った */
const REGISTERED_KEY = "register.done";

/** 自由記載が長すぎる（保存する前の検査）。 */
const FREE_TEXT_TOO_LONG_KEY = "today.free_text_too_long";

const NO_QUESTIONS: readonly Question[] = [];
const NO_ERRORS: ReadonlyMap<string, TemperatureProblem> = new Map();

/**
 * 今日の記録（P1）の本体。段階0「つらくて書けない」→ 段階1 クローズ質問 → 段階2 自由記載。
 * 保存するのは答えたものだけ。空なら保存しない。サーバーへ送るのは日付の印だけで、記録は
 * スマホに置く（plan-device-records §5.2。順序は patient/recordEntry.ts）。
 * 固定規則の案内は画面のコードで判定し、定型文をそのまま出す。
 * client_entry_id は入力の開始時に作り、押し直しても同じ（失敗しても1件にしかならない）。
 * 「つらくて書けない」は必ず確認してから送る。何も入れていなければ3秒で自動で送り、
 * 入れた内容があれば、それを捨てることを確かめてから（「はい」を押した時だけ）送る。
 * 記録した後は TodayDone（要約・取り消し・追加で記録する）。記録できたら onSaved を呼ぶ。
 * 質問集の応答にあるサーバーの今日は onToday で親（見出し）へ渡す。
 * 送って 401/403 なら番号の入力欄に替える。入力はこの部品の state に残るので、同じ番号なら
 * 入力を残して送る前に戻す（押し直すまで送らない）。違う番号は読み直す（質問集も送り先も
 * 別の人のものになるので、入れた内容を持ち越さない）。
 */
export default function TodayForm({
  pid,
  onSaved,
  onToday,
}: {
  pid: string;
  onSaved?: () => void;
  /** 質問集を読めたら、サーバーの今日（YYYY-MM-DD）を渡す（見出しの日付） */
  onToday?: (today: string) => void;
}) {
  const { t } = usePatientStrings();
  const hintId = useId();
  const loaded = useAsync(() => getQuestions(pid), pid);
  const formRef = useRef<HTMLFormElement>(null);
  const [form, setForm] = useState<EntryFormState>(EMPTY_FORM);
  const [phase, setPhase] = useState<Phase>({ name: "editing" });
  const [error, setError] = useState<{ key: string; at: Origin } | null>(null);
  const [temperatureTried, setTemperatureTried] = useState(false);
  const confirm = useTooSickConfirm(hasInput(form));
  const [focusRound, setFocusRound] = useState(0);
  const [infoKey, setInfoKey] = useState<string | null>(null);
  const [clientEntryId, setClientEntryId] = useState(newClientEntryId);

  const today = loaded.status === "ready" ? loaded.data.today : null;
  useEffect(() => {
    if (today !== null) {
      onToday?.(today);
    }
  }, [today, onToday]);

  useEffect(() => {
    if (focusRound > 0) {
      formRef.current
        ?.querySelector<HTMLInputElement>('input[aria-invalid="true"]')
        ?.focus();
    }
  }, [focusRound]);

  const questions =
    loaded.status === "ready" ? loaded.data.questions : NO_QUESTIONS;
  const sending = phase.name === "sending";

  function resumeAfterRegister(registeredPid: string) {
    if (registeredPid !== pid) {
      reloadPage();
      return;
    }
    setInfoKey(REGISTERED_KEY);
    setPhase({ name: "editing" });
  }

  if (loaded.status === "error" && isNotRegistered(loaded.error)) {
    return <NotRegistered />;
  }
  if (phase.name === "not_registered") {
    return <NotRegistered onRegistered={resumeAfterRegister} />;
  }

  function startOver() {
    setClientEntryId(newClientEntryId());
    setForm(EMPTY_FORM);
    setError(null);
    setTemperatureTried(false);
    confirm.close();
    setInfoKey(null);
    setPhase({ name: "editing" });
  }

  function undone() {
    setClientEntryId(newClientEntryId());
    setInfoKey(UNDONE_KEY);
    setPhase({ name: "editing" });
  }

  if (phase.name === "done") {
    return (
      <TodayDone saved={phase.saved} onUndone={undone} onAddMore={startOver} />
    );
  }

  async function send(entry: EntryCreate, doneKey: string, from: Origin) {
    setPhase({ name: "sending", from });
    setError(null);
    setInfoKey(null);
    try {
      // 質問集を読む前に「つらくて書けない」を押したら、ここで読む（記録に版が要る）
      const context =
        loaded.status === "ready" ? loaded.data : await getQuestions(pid);
      const saved = await recordEntry(pid, clientEntryId, entry, context);
      setPhase({
        name: "done",
        saved: {
          entry: saved,
          messageKey: doneKey,
          notices: noticesFor(entry, context.fixed_rules),
        },
      });
      onSaved?.();
    } catch (err) {
      if (isNotRegistered(err)) {
        setPhase({ name: "not_registered" });
        return;
      }
      setError({ key: GENERIC_ERROR_KEY, at: from });
      setPhase({ name: "editing" });
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const result = buildEntry(questions, form);
    if (!result.ok) {
      const badTemperature = result.reason === "temperature_invalid";
      setTemperatureTried(badTemperature);
      setError(
        result.reason === "free_text_too_long"
          ? { key: FREE_TEXT_TOO_LONG_KEY, at: "submit" }
          : null,
      );
      if (badTemperature) {
        setFocusRound((n) => n + 1);
      }
      return;
    }
    void send(result.entry, "today.saved", "submit");
  }

  function sendTooSick() {
    if (sending) {
      return;
    }
    confirm.close();
    void send(
      { too_sick: true, by_proxy: form.byProxy },
      "today.too_sick_done",
      "too_sick",
    );
  }

  const errors = temperatureTried
    ? temperatureErrors(questions, form)
    : NO_ERRORS;
  const showIncomplete =
    loaded.status === "ready" &&
    hasInput(form) &&
    unansweredCount(questions, form) > 0;
  const sendingFrom = phase.name === "sending" ? phase.from : null;
  const blocked = !hasInput(form);

  return (
    <form ref={formRef} onSubmit={handleSubmit} noValidate>
      {infoKey && <DoneMessage messageKey={infoKey} />}
      <ProxyToggle
        checked={form.byProxy}
        disabled={sending}
        onChange={(byProxy) => setForm((prev) => ({ ...prev, byProxy }))}
      />
      <TooSickButton
        confirming={confirm.mode}
        disabled={sending}
        sending={sendingFrom === "too_sick"}
        errorKey={error?.at === "too_sick" ? error.key : null}
        onPress={confirm.open}
        onConfirm={sendTooSick}
        onCancel={confirm.close}
      />

      {loaded.status === "loading" && <Loading />}
      {loaded.status === "error" && <LoadFailed onReload={loaded.reload} />}
      {loaded.status === "ready" && questions.length > 0 && (
        <QuestionList
          questions={questions}
          form={form}
          onChange={setForm}
          temperatureErrors={errors}
          disabled={sending}
        />
      )}

      <FreeTextField
        value={form.freeText}
        disabled={sending}
        onChange={(freeText) => setForm((prev) => ({ ...prev, freeText }))}
      />
      {showIncomplete && <p>{t("today.incomplete")}</p>}
      {error?.at === "submit" && <ErrorMessage messageKey={error.key} />}
      {sendingFrom === "submit" && <SendingMessage />}
      {blocked && (
        <p id={hintId} className="p-hint">
          {t("today.submit_hint")}
        </p>
      )}
      <button
        type="submit"
        className="p-button--primary"
        disabled={sending || blocked}
        aria-describedby={blocked ? hintId : undefined}
      >
        {t("today.submit")}
      </button>
    </form>
  );
}
