import { describe, expect, it } from "vitest";
import type { ChatRow, RegimenDraft } from "../../../api/regimenTypes";
import { fixtureBody } from "../../../test/apiFixtures";
import {
  activeAsk,
  aiCountIn,
  askCovers,
  askKeyOf,
  fieldStateOf,
  openAsk,
  patchTouchesAsk,
  sectionErrors,
  sectionIssues,
  stateTagOf,
} from "./fieldState";
import { changeGroupOf } from "./fieldLabels";

function turnDraft(): RegimenDraft {
  return (fixtureBody("doctor_regimen_draft_turn") as { draft: RegimenDraft })
    .draft;
}

describe("activeAsk", () => {
  it("会話の最後が Claude の ask ならそれ", () => {
    expect(activeAsk(turnDraft())?.field_id).toBe("drugs.drug1.days");
  });

  it("最後が先生の文・失敗の行・ask の無い返答なら無い", () => {
    const draft = turnDraft();
    const doctor: ChatRow = {
      role: "doctor",
      text: "点滴の日は Day1",
      generation: 2,
      at: "2026-11-09T10:00:00+09:00",
    };
    expect(activeAsk({ ...draft, chat: [...draft.chat, doctor] })).toBeNull();
    expect(activeAsk({ ...draft, chat: [] })).toBeNull();
  });
});

describe("askCovers", () => {
  const ask = { field_id: "drugs", question: "？", options: [] };
  it("節の名前なら節の中の欄を全て含む", () => {
    expect(askCovers(ask, "drugs.drug1.days")).toBe(true);
    expect(askCovers(ask, "drugs")).toBe(true);
    expect(askCovers(ask, "side_effects.x.phrases")).toBe(false);
    expect(askCovers(null, "drugs")).toBe(false);
  });
});

describe("fieldStateOf（4つの状態）", () => {
  it("ask の欄は赤枠（未入力より強い）", () => {
    const draft = turnDraft();
    expect(fieldStateOf(draft, "drugs.drug1.days", activeAsk(draft))).toBe(
      "asked",
    );
  });

  it("必須の欠けはピンク", () => {
    const draft = turnDraft();
    expect(fieldStateOf(draft, "basic.code", activeAsk(draft))).toBe("missing");
  });

  it("standard だけが AI が入れた。doctor_text と doctor_edit は先生の青枠", () => {
    const draft: RegimenDraft = {
      ...turnDraft(),
      sources: {
        ...turnDraft().sources,
        "basic.display_name": "doctor_edit",
      },
    };
    expect(draft.sources["basic.target"]).toBe("standard");
    expect(fieldStateOf(draft, "basic.target", null)).toBe("ai");
    expect(draft.sources["basic.cycle_days"]).toBe("doctor_text");
    expect(fieldStateOf(draft, "basic.cycle_days", null)).toBe("doc");
    expect(fieldStateOf(draft, "basic.display_name", null)).toBe("doc");
    expect(fieldStateOf(draft, "notes", null)).toBe("plain");
  });

  it("先生の文からの欄でも、ask の欄なら赤枠のまま（答えるまで）", () => {
    const draft = turnDraft();
    const ask = { field_id: "basic.cycle_days", question: "？", options: [] };
    expect(fieldStateOf(draft, "basic.cycle_days", ask)).toBe("asked");
  });

  it("先生が直接入れた欄は ask を指していても赤枠にしない（答えた）", () => {
    const draft = turnDraft();
    const answered = {
      ...draft,
      sources: { ...draft.sources, "drugs.drug1.days": "doctor_edit" as const },
      missing: draft.missing.filter((m) => m.field_id !== "drugs.drug1.days"),
    };
    expect(
      fieldStateOf(answered, "drugs.drug1.days", activeAsk(answered)),
    ).toBe("doc");
  });
});

describe("stateTagOf", () => {
  it("文字の札（青枠の札は出どころで出し分ける）", () => {
    expect(stateTagOf("missing")).toBe("未入力（必須）");
    expect(stateTagOf("asked")).toBe("Claude が聞いています");
    expect(stateTagOf("ai", "standard")).toBe("AI が入れた（標準の値）");
    expect(stateTagOf("doc", "doctor_edit")).toBe("先生が入れた");
    expect(stateTagOf("doc", "doctor_text")).toBe("先生の文から");
    expect(stateTagOf("plain")).toBe("");
  });
});

describe("aiCountIn・sectionIssues", () => {
  it("節ごとの AI の欄の数（standard だけ）と、節の単位の欠け", () => {
    const draft = turnDraft();
    expect(aiCountIn(draft, "basic")).toBe(1);
    expect(aiCountIn(draft, "drugs")).toBe(1);
    expect(aiCountIn(draft, "questions")).toBe(0);
    expect(sectionIssues(draft, "drugs").map((m) => m.code)).toEqual([
      "day1_infusion",
    ]);
  });
});

describe("changeGroupOf（変えた欄の札）", () => {
  it("基本は欄ごと、行は行の名前でまとめる", () => {
    const form = turnDraft().form;
    expect(changeGroupOf(form, "basic.cycle_days")).toEqual({
      key: "basic.cycle_days",
      label: "基本 · 1コースの日数",
    });
    expect(changeGroupOf(form, "drugs.drug1.route")).toEqual({
      key: "drugs.drug1",
      label: "薬 · ベバシズマブ",
    });
    expect(changeGroupOf(form, "questions.question1.text").label).toBe(
      "質問 · 下痢",
    );
    expect(changeGroupOf(form, "notes").label).toBe("補足の指示");
    expect(changeGroupOf(form, "drugs.gone.name").label).toBe(
      "薬 · （消した行）",
    );
  });
});

describe("openAsk", () => {
  it("会話の最後の ask で、答えた目印も直接の編集も無ければ生きている", () => {
    expect(openAsk(turnDraft(), null)?.field_id).toBe("drugs.drug1.days");
  });

  it("この ask の目印で答えたなら無い。会話が伸びた後の古い目印は効かない", () => {
    const draft = turnDraft();
    expect(openAsk(draft, askKeyOf(draft))).toBeNull();
    expect(
      openAsk(draft, `${draft.id}:${draft.chat.length - 1}`),
    ).not.toBeNull();
  });

  it("ask の欄を先生が直接入れていれば（doctor_edit）無い", () => {
    const draft = turnDraft();
    expect(
      openAsk(
        {
          ...draft,
          sources: { ...draft.sources, "drugs.drug1.days": "doctor_edit" },
        },
        null,
      ),
    ).toBeNull();
  });
});

describe("patchTouchesAsk", () => {
  const ask = { field_id: "drugs", question: "薬は？", options: [] };

  it("節の ask は、その節の欄の変更・行の追加と削除で触れる", () => {
    expect(
      patchTouchesAsk(ask, {
        changes: [{ field_id: "drugs.d-bv.days", value: [] }],
      }),
    ).toBe(true);
    expect(
      patchTouchesAsk(ask, {
        adds: [{ section: "drugs", row_id: "drug-add-a" }],
      }),
    ).toBe(true);
    expect(patchTouchesAsk(ask, { deletes: ["drugs.d-bv"] })).toBe(true);
  });

  it("ほかの節・ask が無いときは触れない", () => {
    expect(
      patchTouchesAsk(ask, { changes: [{ field_id: "notes", value: "" }] }),
    ).toBe(false);
    expect(
      patchTouchesAsk(null, {
        changes: [{ field_id: "drugs.d-bv.days", value: [] }],
      }),
    ).toBe(false);
  });
});

describe("sectionErrors", () => {
  const errors = {
    drugs: ["薬を1剤以上"],
    "drugs.drug-add-a": ["同じ行がもうあります"],
    "drugs.#1": ["行の形が違う"],
    "drugs.d-bv.days": ["欄の理由"],
    "basic.cycle_days": ["基本の欄の理由"],
  };

  it("行の節は、節の名前の欄と行の単位の欄の理由を出す（欄の理由は出さない）", () => {
    expect(sectionErrors(errors, "drugs")).toEqual([
      "薬を1剤以上",
      "同じ行がもうあります",
      "行の形が違う",
    ]);
  });

  it("基本の節の欄（basic.cycle_days）は行ではないので出さない", () => {
    expect(sectionErrors(errors, "basic")).toEqual([]);
  });
});
