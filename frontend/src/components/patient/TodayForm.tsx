import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { isApiError } from "../../api/http";
import { createEntry, getQuestions } from "../../api/patient";
import type { EntryCreate, Question } from "../../api/types";
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
import { summarizeEntry, summarySourceOf } from "./entrySummary";
import FreeTextField from "./FreeTextField";
import { LoadFailed, Loading } from "./LoadStatus";
import { DoneMessage, ErrorMessage } from "./Messages";
import {
  GENERIC_ERROR_KEY,
  NOT_REGISTERED_KEY,
  isNotRegistered,
} from "./patientApi";
import ProxyToggle from "./ProxyToggle";
import QuestionList from "./QuestionList";
import TodayDone, { type SavedRecord } from "./TodayDone";
import TooSickButton, { SendingMessage } from "./TooSickButton";
import { useAsync } from "./useAsync";

/** どちらのボタンから送ったか（送信中・失敗の知らせをそのボタンの近くに出す）。 */
type Origin = "too_sick" | "submit";

type Phase =
  | { name: "editing" }
  | { name: "sending"; from: Origin }
  | { name: "done"; saved: SavedRecord }
  | { name: "not_registered" };

/** 「取り消しました」（取り消して記録する前の画面に戻った） */
const UNDONE_KEY = "today.undone";

/** 自由記載が長すぎる（送る前の検査と、サーバーの 422 free_text_too_long）。 */
const FREE_TEXT_TOO_LONG_KEY = "today.free_text_too_long";

const NO_QUESTIONS: readonly Question[] = [];
const NO_ERRORS: ReadonlyMap<string, TemperatureProblem> = new Map();

/**
 * 今日の記録（P1）の本体。段階0「つらくて書けない」→ 段階1 クローズ質問 → 段階2 自由記載。
 * 送るのは答えたものだけ。空なら送らない。送信後は notices の定型文をそのまま出す。
 * 入力済みで「つらくて書けない」を押したら、入力を捨てることを確かめてから送る。
 * 記録した後は TodayDone（要約・取り消し・追加で記録する）。記録できたら onSaved を呼ぶ。
 */
export default function TodayForm({
  pid,
  onSaved,
}: {
  pid: string;
  onSaved?: () => void;
}) {
  const { t } = usePatientStrings();
  const hintId = useId();
  const loaded = useAsync(() => getQuestions(pid), pid);
  const formRef = useRef<HTMLFormElement>(null);
  const [form, setForm] = useState<EntryFormState>(EMPTY_FORM);
  const [phase, setPhase] = useState<Phase>({ name: "editing" });
  const [error, setError] = useState<{ key: string; at: Origin } | null>(null);
  const [temperatureTried, setTemperatureTried] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [focusRound, setFocusRound] = useState(0);
  const [infoKey, setInfoKey] = useState<string | null>(null);

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

  if (
    phase.name === "not_registered" ||
    (loaded.status === "error" && isNotRegistered(loaded.error))
  ) {
    return <ErrorMessage messageKey={NOT_REGISTERED_KEY} />;
  }

  function startOver() {
    setForm(EMPTY_FORM);
    setError(null);
    setTemperatureTried(false);
    setConfirming(false);
    setInfoKey(null);
    setPhase({ name: "editing" });
  }

  function undone() {
    setInfoKey(UNDONE_KEY);
    setPhase({ name: "editing" });
  }

  if (phase.name === "done") {
    return (
      <TodayDone
        pid={pid}
        saved={phase.saved}
        onUndone={undone}
        onAddMore={startOver}
      />
    );
  }

  async function send(entry: EntryCreate, doneKey: string, from: Origin) {
    setPhase({ name: "sending", from });
    setError(null);
    setInfoKey(null);
    try {
      const res = await createEntry(pid, entry);
      const saved: SavedRecord = {
        entryId: res.entry_id,
        messageKey: doneKey,
        notices: res.notices,
        items: summarizeEntry(summarySourceOf(entry, questions)),
        undoable: entry.too_sick === true,
      };
      setPhase({ name: "done", saved });
      onSaved?.();
    } catch (err) {
      if (isNotRegistered(err)) {
        setPhase({ name: "not_registered" });
        return;
      }
      const tooLong = isApiError(err) && err.code === "free_text_too_long";
      setError({
        key: tooLong ? FREE_TEXT_TOO_LONG_KEY : GENERIC_ERROR_KEY,
        at: from,
      });
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
    setConfirming(false);
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
        confirming={confirming}
        disabled={sending}
        sending={sendingFrom === "too_sick"}
        errorKey={error?.at === "too_sick" ? error.key : null}
        onPress={() => (hasInput(form) ? setConfirming(true) : sendTooSick())}
        onConfirm={sendTooSick}
        onCancel={() => setConfirming(false)}
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
