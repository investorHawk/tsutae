import { useState, type FormEvent } from "react";
import { createEntry, getQuestions } from "../../api/patient";
import type { EntryCreate, Question } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";
import {
  EMPTY_FORM,
  buildEntry,
  hasInput,
  invalidTemperatureKeys,
  unansweredCount,
  type EntryFormState,
} from "./entryForm";
import FreeTextField from "./FreeTextField";
import { DoneMessage, ErrorMessage, Notices } from "./Messages";
import {
  GENERIC_ERROR_KEY,
  NOT_REGISTERED_KEY,
  isNotRegistered,
} from "./patientApi";
import ProxyToggle from "./ProxyToggle";
import QuestionList from "./QuestionList";
import { useAsync } from "./useAsync";

type Phase =
  | { name: "editing" }
  | { name: "sending" }
  | { name: "done"; messageKey: string; notices: readonly string[] }
  | { name: "not_registered" };

/**
 * 自由記載が長すぎるときの定型文。専用のキーが patient_strings.json に無いので、
 * サーバーが同じ入力を 422 で拒んだときと同じ error.generic を出す（契約への要望で専用キーを依頼中）。
 */
const FREE_TEXT_TOO_LONG_KEY = GENERIC_ERROR_KEY;

const NO_QUESTIONS: readonly Question[] = [];
const NO_KEYS: ReadonlySet<string> = new Set();

/**
 * 今日の記録（P1）の本体。段階0「つらくて書けない」→ 段階1 クローズ質問 → 段階2 自由記載。
 * 送るのは答えたものだけ。空なら送らない。送信後は notices の定型文をそのまま出す。
 */
export default function TodayForm({ pid }: { pid: string }) {
  const { t } = usePatientStrings();
  const loaded = useAsync(() => getQuestions(pid), pid);
  const [form, setForm] = useState<EntryFormState>(EMPTY_FORM);
  const [phase, setPhase] = useState<Phase>({ name: "editing" });
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [temperatureTried, setTemperatureTried] = useState(false);

  const questions =
    loaded.status === "ready" ? loaded.data.questions : NO_QUESTIONS;
  const sending = phase.name === "sending";

  if (
    phase.name === "not_registered" ||
    (loaded.status === "error" && isNotRegistered(loaded.error))
  ) {
    return <ErrorMessage messageKey={NOT_REGISTERED_KEY} />;
  }
  if (phase.name === "done") {
    return (
      <>
        <DoneMessage messageKey={phase.messageKey} />
        <Notices keys={phase.notices} />
      </>
    );
  }

  async function send(entry: EntryCreate, doneKey: string) {
    setPhase({ name: "sending" });
    setErrorKey(null);
    try {
      const res = await createEntry(pid, entry);
      setPhase({ name: "done", messageKey: doneKey, notices: res.notices });
    } catch (err) {
      if (isNotRegistered(err)) {
        setPhase({ name: "not_registered" });
        return;
      }
      setErrorKey(GENERIC_ERROR_KEY);
      setPhase({ name: "editing" });
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const result = buildEntry(questions, form);
    if (!result.ok) {
      setTemperatureTried(result.reason === "temperature_invalid");
      setErrorKey(
        result.reason === "free_text_too_long" ? FREE_TEXT_TOO_LONG_KEY : null,
      );
      return;
    }
    void send(result.entry, "today.saved");
  }

  function handleTooSick() {
    void send(
      { too_sick: true, by_proxy: form.byProxy },
      "today.too_sick_done",
    );
  }

  const invalidTemperatures = temperatureTried
    ? invalidTemperatureKeys(questions, form)
    : NO_KEYS;
  const showIncomplete =
    loaded.status === "ready" &&
    hasInput(form) &&
    unansweredCount(questions, form) > 0;

  return (
    <form onSubmit={handleSubmit} noValidate>
      <ProxyToggle
        checked={form.byProxy}
        disabled={sending}
        onChange={(byProxy) => setForm((prev) => ({ ...prev, byProxy }))}
      />
      <button
        type="button"
        className="p-button--too-sick"
        disabled={sending}
        onClick={handleTooSick}
      >
        {t("today.too_sick_button")}
      </button>

      {loaded.status === "error" && (
        <ErrorMessage messageKey={GENERIC_ERROR_KEY} />
      )}
      {loaded.status === "ready" && questions.length > 0 && (
        <QuestionList
          questions={questions}
          form={form}
          onChange={setForm}
          invalidTemperatureKeys={invalidTemperatures}
          disabled={sending}
        />
      )}

      <FreeTextField
        value={form.freeText}
        disabled={sending}
        onChange={(freeText) => setForm((prev) => ({ ...prev, freeText }))}
      />
      {showIncomplete && <p>{t("today.incomplete")}</p>}
      {errorKey && <ErrorMessage messageKey={errorKey} />}
      <button
        type="submit"
        className="p-button--primary"
        disabled={sending || !hasInput(form)}
      >
        {t("today.submit")}
      </button>
    </form>
  );
}
