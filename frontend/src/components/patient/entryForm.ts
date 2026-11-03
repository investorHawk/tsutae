/**
 * 今日の記録（P1）の入力を EntryCreate に直す純関数。
 * 送るのは答えた質問だけ（未回答は送らない）。何も無ければ送らない（spec 4.1）。
 */
import type {
  AnswerValue,
  ClosedAnswer,
  EntryCreate,
  Question,
} from "../../api/types";
import {
  FEVER_VALUES,
  TEMPERATURE_MAX,
  TEMPERATURE_MIN,
  THREE_LEVEL_VALUES,
} from "../../api/types";

export { TEMPERATURE_MAX, TEMPERATURE_MIN };
/**
 * 自由記載の上限（schemas.py EntryCreate.free_text。Python の文字数＝code point で数える）。
 * native の maxLength は UTF-16 単位なので使わず、buildEntry で検査する。
 */
export const FREE_TEXT_MAX = 2000;

/** 整数部と任意桁の小数（範囲は別に検査する。schemas.py は桁数を制限しない）。 */
const TEMPERATURE_PATTERN = /^\d{1,3}(\.\d+)?$/;

export interface EntryFormState {
  /** question_key → 押した答え。押していない質問はキーが無い。 */
  answers: Readonly<Record<string, AnswerValue>>;
  /**
   * question_key → 体温の入力欄（「測った」のときだけ使う）。体温の質問が2つ以上あっても
   * 値を共有しないよう、質問ごとに持つ。
   */
  temperatureTexts: Readonly<Record<string, string>>;
  freeText: string;
  byProxy: boolean;
}

export const EMPTY_FORM: EntryFormState = Object.freeze({
  answers: Object.freeze({}),
  temperatureTexts: Object.freeze({}),
  freeText: "",
  byProxy: false,
});

export type BuildResult =
  | { ok: true; entry: EntryCreate }
  | {
      ok: false;
      reason: "empty" | "temperature_invalid" | "free_text_too_long";
    };

/**
 * 体温の入力の問題。数字の形でない（空を含む）なら invalid（temperature.invalid）、
 * 数字だが 30〜45 の外（小数点の打ち忘れの 368 など）なら out_of_range
 * （temperature.out_of_range）。正しければ null。全角は半角に直してから見る。
 */
export type TemperatureProblem = "invalid" | "out_of_range";

function normalizeTemperature(text: string): string {
  return text.normalize("NFKC").trim();
}

export function temperatureProblem(text: string): TemperatureProblem | null {
  const normalized = normalizeTemperature(text);
  if (!TEMPERATURE_PATTERN.test(normalized)) {
    return "invalid";
  }
  const value = Number(normalized);
  if (value < TEMPERATURE_MIN || value > TEMPERATURE_MAX) {
    return "out_of_range";
  }
  return null;
}

/** 体温の文字列を数値にする。全角は半角に直す。30〜45 の範囲だけ。不正なら null。 */
export function parseTemperature(text: string): number | null {
  if (temperatureProblem(text) !== null) {
    return null;
  }
  return Number(normalizeTemperature(text));
}

/** 答えを入れた新しい状態を返す。同じ答えを押し直すと取り消す。 */
export function setAnswer(
  state: EntryFormState,
  key: string,
  value: AnswerValue,
): EntryFormState {
  if (state.answers[key] === value) {
    const rest = Object.fromEntries(
      Object.entries(state.answers).filter(([k]) => k !== key),
    );
    return { ...state, answers: rest };
  }
  return { ...state, answers: { ...state.answers, [key]: value } };
}

/** その質問の体温の入力欄だけを変えた新しい状態を返す。 */
export function setTemperatureText(
  state: EntryFormState,
  key: string,
  text: string,
): EntryFormState {
  return {
    ...state,
    temperatureTexts: { ...state.temperatureTexts, [key]: text },
  };
}

/** その質問の体温（入力欄が無ければ空として検査する）。不正なら null。 */
function temperatureOf(state: EntryFormState, key: string): number | null {
  return parseTemperature(state.temperatureTexts[key] ?? "");
}

function fitsQuestion(question: Question, value: AnswerValue): boolean {
  const allowed: readonly AnswerValue[] =
    question.answer_type === "temperature" ? FEVER_VALUES : THREE_LEVEL_VALUES;
  return allowed.includes(value);
}

/** 質問集の順に、答えた質問だけを並べる（型の合わない答えは捨てる）。 */
function answeredPairs(
  questions: readonly Question[],
  state: EntryFormState,
): Array<{ question: Question; value: AnswerValue }> {
  return questions.flatMap((question) => {
    const value = state.answers[question.key];
    return value !== undefined && fitsQuestion(question, value)
      ? [{ question, value }]
      : [];
  });
}

/** 「測った」のに体温が不正な質問の key → 問題（質問集の順）。 */
export function temperatureErrors(
  questions: readonly Question[],
  state: EntryFormState,
): ReadonlyMap<string, TemperatureProblem> {
  return new Map(
    answeredPairs(questions, state).flatMap(({ question, value }) => {
      if (value !== "measured") {
        return [];
      }
      const problem = temperatureProblem(
        state.temperatureTexts[question.key] ?? "",
      );
      return problem === null ? [] : [[question.key, problem] as const];
    }),
  );
}

/** 「測った」のに体温が不正な質問の key（質問集の順）。 */
export function invalidTemperatureKeys(
  questions: readonly Question[],
  state: EntryFormState,
): ReadonlySet<string> {
  return new Set(temperatureErrors(questions, state).keys());
}

export function unansweredCount(
  questions: readonly Question[],
  state: EntryFormState,
): number {
  return questions.length - answeredPairs(questions, state).length;
}

export function hasInput(state: EntryFormState): boolean {
  return (
    Object.keys(state.answers).length > 0 || state.freeText.trim().length > 0
  );
}

export function buildEntry(
  questions: readonly Question[],
  state: EntryFormState,
): BuildResult {
  const answers: ClosedAnswer[] = [];
  for (const { question, value } of answeredPairs(questions, state)) {
    if (value !== "measured") {
      answers.push({ question_key: question.key, value });
      continue;
    }
    const temperature = temperatureOf(state, question.key);
    if (temperature === null) {
      return { ok: false, reason: "temperature_invalid" };
    }
    answers.push({ question_key: question.key, value, temperature });
  }
  const freeText = state.freeText.trim();
  if ([...freeText].length > FREE_TEXT_MAX) {
    return { ok: false, reason: "free_text_too_long" };
  }
  if (answers.length === 0 && freeText.length === 0) {
    return { ok: false, reason: "empty" };
  }
  return {
    ok: true,
    entry: {
      by_proxy: state.byProxy,
      answers,
      free_text: freeText.length > 0 ? freeText : null,
    },
  };
}
