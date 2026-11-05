/**
 * D4 レジメンの画面テスト用（本番コードからは import しない）。本物の Claude の smoke
 * （docs/eval/demo-regimen-20261105-0857.json）で出来た FOLFIRI＋BV の形を組む:
 * 基本と薬は先生の文から、副作用と質問（体温の q-fever を除く）は標準の値。
 */
import type {
  AiValue,
  DrugRow,
  FieldSource,
  QuestionRow,
  RegimenDraft,
  RegimenPreview,
  SideEffectRow,
} from "../../../api/regimenTypes";
import { draftOf, previewOf } from "./regimenTesting";

const DRUGS: readonly DrugRow[] = (
  [
    ["drug1", "ベバシズマブ", "infusion", 1],
    ["drug2", "イリノテカン", "infusion", 1],
    ["drug3", "レボホリナート", "infusion", 1],
    ["drug4", "フルオロウラシル（急速静注）", "infusion", 1],
    ["drug5", "フルオロウラシル（46時間持続）", "pump", 3],
  ] as const
).map(([row_id, name, route, end]) => ({
  row_id,
  name,
  route,
  days: [{ start: 1, end }],
  times_per_day: null,
  start_note: null,
}));

const EFFECTS: readonly SideEffectRow[] = [
  ["effect1", ["下痢", "お腹がゆるい"], ["下痢"], "diarrhea"],
  [
    "effect2",
    ["吐き気", "食欲がない", "吐いた"],
    ["悪心", "嘔吐", "食欲不振"],
    "nausea_appetite",
  ],
  ["effect3", ["口内炎", "口の中が痛い"], ["口腔粘膜炎"], "stomatitis"],
  ["effect4", ["だるい", "疲れやすい"], ["疲労", "倦怠感"], "fatigue"],
  ["effect5", ["熱が出た", "寒気"], ["発熱", "悪寒"], "fever"],
  ["effect6", ["鼻血"], ["鼻出血"], "bleeding"],
  ["effect7", ["髪が抜ける"], ["脱毛症"], null],
].map(([row_id, phrases, ctcae_terms, question_key]) => ({
  row_id: row_id as string,
  phrases: phrases as string[],
  ctcae_terms: ctcae_terms as string[],
  question_key: question_key as string | null,
}));

const QUESTIONS: readonly QuestionRow[] = [
  ["question1", "diarrhea", "下痢", "下痢はありましたか"],
  [
    "question2",
    "nausea_appetite",
    "吐き気・食欲",
    "吐き気や食欲の落ち込みはありましたか",
  ],
  ["question3", "stomatitis", "口内炎", "口の中の痛みや口内炎はありましたか"],
  ["question4", "fatigue", "だるさ", "だるさや疲れやすさはありましたか"],
  ["question5", "bleeding", "出血", "鼻血や歯ぐきからの出血はありましたか"],
].map(([row_id, key, label, text]) => ({
  row_id,
  key,
  label,
  text,
  answer_type: "three_level" as const,
}));

const FEVER: QuestionRow = {
  row_id: "q-fever",
  key: "fever",
  label: "体温",
  text: "熱を測りましたか",
  answer_type: "temperature",
};

/** 値が入っている欄の id（row_id 以外。空の欄は出どころを持たない）。 */
function filledIds(section: string, row: { row_id: string }): string[] {
  return Object.entries(row)
    .filter(
      ([name, value]) =>
        name !== "row_id" &&
        value !== null &&
        !(Array.isArray(value) && value.length === 0),
    )
    .map(([name]) => `${section}.${row.row_id}.${name}`);
}

function sourcesOf(
  ids: readonly string[],
  source: FieldSource,
): Record<string, FieldSource> {
  return Object.fromEntries(ids.map((id) => [id, source]));
}

function demoSources(): Record<string, FieldSource> {
  return {
    ...sourcesOf(
      [
        "basic.display_name",
        "basic.code",
        "basic.target",
        "basic.cycle_days",
        ...DRUGS.flatMap((d) => filledIds("drugs", d)),
      ],
      "doctor_text",
    ),
    ...sourcesOf(
      [
        ...EFFECTS.flatMap((e) => filledIds("side_effects", e)),
        ...QUESTIONS.flatMap((q) => filledIds("questions", q)),
      ],
      "standard",
    ),
  };
}

/** smoke と同じ形の下書き（id 1。必須はそろっている）。 */
export function demoDraft(): RegimenDraft {
  const draft = draftOf("doctor_regimen_draft");
  return {
    ...draft,
    form: {
      basic: {
        display_name: "FOLFIRI＋BV",
        code: "FOLFIRI-BV",
        target: "大腸がん",
        cycle_days: 14,
      },
      drugs: [...DRUGS],
      side_effects: [...EFFECTS],
      questions: [FEVER, ...QUESTIONS],
      notes: "",
    },
    sources: demoSources(),
    missing: [],
    chat: [],
  };
}

const FIELD_LABELS: Readonly<Record<string, string>> = {
  phrases: "患者の言い方",
  ctcae_terms: "CTCAE の用語",
  question_key: "対応する質問",
  key: "key",
  label: "短い名前",
  text: "患者に出る文",
  answer_type: "回答の型",
};

function aiValuesOf<R extends { row_id: string }>(
  section: string,
  rows: readonly R[],
  nameOf: (row: R) => string,
): AiValue[] {
  return rows.flatMap((row) =>
    filledIds(section, row).map((field_id) => {
      const name = field_id.split(".")[2];
      return {
        field_id,
        label: `${nameOf(row)} — ${FIELD_LABELS[name]}`,
        value: (row as Readonly<Record<string, unknown>>)[name],
        source: "standard" as const,
      };
    }),
  );
}

/** preview の ai_values（backend の ai_values と同じ形・同じ並び。副作用 → 質問）。 */
export function demoAiValues(): AiValue[] {
  return [
    ...aiValuesOf(
      "side_effects",
      EFFECTS,
      (r: SideEffectRow) => r.phrases[0] ?? "副作用",
    ),
    ...aiValuesOf(
      "questions",
      QUESTIONS,
      (r: QuestionRow) => r.label ?? "質問",
    ),
  ];
}

export function demoPreview(): RegimenPreview {
  return {
    ...previewOf("doctor_regimen_draft_preview"),
    ai_values: demoAiValues(),
  };
}
