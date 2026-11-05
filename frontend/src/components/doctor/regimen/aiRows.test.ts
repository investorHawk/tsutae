import { describe, expect, it } from "vitest";
import type { AiValue } from "../../../api/regimenTypes";
import { aiRowCountOf, aiRowsOf, deletePatchOf } from "./aiRows";
import { demoAiValues, demoDraft } from "./regimenTestingDemo";

function value(field_id: string, label: string, v: unknown): AiValue {
  return { field_id, label, value: v, source: "standard" };
}

describe("aiRowsOf の値の文（医師に内部の値を見せない）", () => {
  it("質問の key は出さず、回答の型と対応する質問は日本語で出す。key の欄は削除の対象に残す", () => {
    const [question, effect, noLink] = aiRowsOf(
      [
        value("questions.q1.key", "だるさ — key", "fatigue"),
        value("questions.q1.label", "だるさ — 短い名前", "だるさ"),
        value("questions.q1.answer_type", "だるさ — 回答の型", "three_level"),
        value(
          "side_effects.e1.question_key",
          "だるい — 対応する質問",
          "fatigue",
        ),
        value("side_effects.e2.question_key", "髪 — 対応する質問", null),
      ],
      [{ key: "fatigue", label: "だるさ" }],
    );
    expect(question.text).toBe("短い名前: だるさ／回答の型: 3択");
    expect(question.fieldIds).toContain("questions.q1.key");
    expect(effect.text).toBe("対応する質問: だるさ");
    expect(noLink.text).toBe("対応する質問: （空）");
  });
});

describe("aiRowsOf（AI が入れた値を行にまとめる）", () => {
  const rows = aiRowsOf([
    value("basic.target", "対象", "大腸がん"),
    value("basic.cycle_days", "1コースの日数", 14),
    value("drugs.d1.name", "ベバシズマブ — 薬の名前", "ベバシズマブ"),
    value("drugs.d1.days", "ベバシズマブ — Day", [{ start: 1, end: 1 }]),
    value("drugs.d2.name", "イリノテカン — 薬の名前", "イリノテカン"),
    value("side_effects.e1.phrases", "下痢 — 患者の言い方", ["下痢", "軟便"]),
    value("questions.q1.label", "下痢 — 短い名前", "下痢"),
    value("notes", "補足の指示", "院内の決まり"),
  ]);

  it("行の節は行ごとに1つ、基本と補足の指示は欄ごとに1つ。並びは入力のまま", () => {
    expect(rows.map((r) => r.key)).toEqual([
      "basic.target",
      "basic.cycle_days",
      "drugs.d1",
      "drugs.d2",
      "side_effects.e1",
      "questions.q1",
      "notes",
    ]);
    expect(rows[2].fieldIds).toEqual(["drugs.d1.name", "drugs.d1.days"]);
  });

  it("行の名前は「 — 」より前、値は「欄の名前: 値」を「／」でつなぐ", () => {
    expect(rows[2].name).toBe("ベバシズマブ");
    expect(rows[2].text).toBe("薬の名前: ベバシズマブ／Day: Day1");
    expect(rows[4].text).toBe("患者の言い方: 下痢、軟便");
  });

  it("「 — 」の無い欄（基本・補足の指示）は名前がそのまま欄の名前で、値だけを出す", () => {
    expect(rows[0]).toMatchObject({ name: "対象", text: "大腸がん" });
    expect(rows[1]).toMatchObject({ name: "1コースの日数", text: "14" });
    expect(rows[6]).toMatchObject({ name: "補足の指示", text: "院内の決まり" });
  });

  it("同じ名前の副作用と質問を節の名前で見分ける", () => {
    expect(rows[4].where).toBe("副作用 · 下痢");
    expect(rows[5].where).toBe("質問 · 下痢");
    expect(rows[2].where).toBe("薬 · ベバシズマブ");
    expect(rows[0].where).toBe("対象");
  });

  it("名前に「 — 」があっても、最後の区切りで切る", () => {
    const [row] = aiRowsOf([
      value("drugs.d1.route", "A — B — 経路", "infusion"),
    ]);
    expect(row).toMatchObject({ name: "A — B", text: "経路: 点滴" });
  });

  it("元の配列は変えない", () => {
    const input = [value("basic.target", "対象", "大腸がん")];
    const copy = structuredClone(input);
    aiRowsOf(input);
    expect(input).toEqual(copy);
  });

  it("FOLFIRI＋BV の smoke の形は 40 欄が 12 行（質問5・副作用7）", () => {
    const values = demoAiValues();
    const demo = aiRowsOf(values);
    expect(values).toHaveLength(40);
    expect(demo).toHaveLength(12);
    expect(demo.filter((r) => r.section === "side_effects")).toHaveLength(7);
    expect(demo.filter((r) => r.section === "questions")).toHaveLength(5);
  });
});

describe("aiRowCountOf（sources の id から同じ数え方で）", () => {
  it("standard だけを、行ごと・欄ごとに数える", () => {
    expect(
      aiRowCountOf({
        "basic.target": "standard",
        "basic.cycle_days": "doctor_text",
        "drugs.d1.name": "standard",
        "drugs.d1.days": "standard",
        "drugs.d2.name": "doctor_edit",
        notes: "standard",
      }),
    ).toBe(3);
    expect(aiRowCountOf({})).toBe(0);
  });

  it("smoke の形で aiRowsOf と同じ 12", () => {
    expect(aiRowCountOf(demoDraft().sources)).toBe(12);
  });
});

describe("deletePatchOf（確認の画面の「削除」が送る PATCH）", () => {
  const rowOf = (key: string) => {
    const row = aiRowsOf(demoAiValues()).find((r) => r.key === key);
    if (!row) {
      throw new Error(`行が無い: ${key}`);
    }
    return row;
  };

  it("値が入っている欄が全て standard の副作用の行は、行ごと消す", () => {
    const { body, fieldIds } = deletePatchOf(
      demoDraft(),
      rowOf("side_effects.effect7"),
    );
    expect(body).toEqual({ deletes: ["side_effects.effect7"] });
    expect(fieldIds).toEqual(["side_effects", "side_effects.effect7"]);
  });

  it("質問の行を消すときは、その key を指す副作用の question_key を同じ PATCH で空にする", () => {
    const { body, fieldIds } = deletePatchOf(
      demoDraft(),
      rowOf("questions.question1"),
    );
    expect(body).toEqual({
      deletes: ["questions.question1"],
      changes: [{ field_id: "side_effects.effect1.question_key", value: null }],
    });
    expect(fieldIds).toContain("side_effects.effect1.question_key");
  });

  it("どの副作用からも指されていない質問は、行を消すだけ", () => {
    const draft = demoDraft();
    const form = {
      ...draft.form,
      side_effects: draft.form.side_effects.map((e) => ({
        ...e,
        question_key: e.question_key === "diarrhea" ? null : e.question_key,
      })),
    };
    expect(
      deletePatchOf({ ...draft, form }, rowOf("questions.question1")).body,
    ).toEqual({ deletes: ["questions.question1"] });
  });

  it("先生が入れた欄が混ざる行は、standard の欄だけを空にする", () => {
    const draft = demoDraft();
    const sources = {
      ...draft.sources,
      "side_effects.effect1.phrases": "doctor_edit" as const,
    };
    expect(
      deletePatchOf({ ...draft, sources }, rowOf("side_effects.effect1")).body,
    ).toEqual({
      changes: [
        { field_id: "side_effects.effect1.ctcae_terms", value: [] },
        { field_id: "side_effects.effect1.question_key", value: null },
      ],
    });
  });

  it("先生の文からの欄が混ざる行も、standard の欄だけを空にする", () => {
    const draft = demoDraft();
    const sources = {
      ...draft.sources,
      "questions.question2.text": "doctor_text" as const,
    };
    const { body } = deletePatchOf(
      { ...draft, sources },
      rowOf("questions.question2"),
    );
    expect(body.deletes).toBeUndefined();
    expect(body.changes?.map((c) => c.field_id)).toEqual([
      "questions.question2.key",
      "questions.question2.label",
      "questions.question2.answer_type",
      "side_effects.effect2.question_key",
    ]);
  });

  it("出どころの無い欄（既存の版から開いた値）が混ざる行は、行を消さない", () => {
    const draft = demoDraft();
    const { "questions.question3.label": _removed, ...sources } = draft.sources;
    const { body } = deletePatchOf(
      { ...draft, sources },
      rowOf("questions.question3"),
    );
    expect(body.deletes).toBeUndefined();
    expect(body.changes).toContainEqual({
      field_id: "questions.question3.text",
      value: null,
    });
    expect(body.changes).not.toContainEqual({
      field_id: "questions.question3.label",
      value: null,
    });
  });

  it("先生の欄が混ざる質問でも、key を空にするなら指している副作用も空にする", () => {
    const draft = demoDraft();
    const sources = {
      ...draft.sources,
      "questions.question1.text": "doctor_edit" as const,
    };
    const { body } = deletePatchOf(
      { ...draft, sources },
      rowOf("questions.question1"),
    );
    expect(body.changes).toContainEqual({
      field_id: "side_effects.effect1.question_key",
      value: null,
    });
  });

  it("key が先生の欄なら key は残るので、指している副作用には触らない", () => {
    const draft = demoDraft();
    const sources = {
      ...draft.sources,
      "questions.question1.key": "doctor_edit" as const,
    };
    const { body } = deletePatchOf(
      { ...draft, sources },
      rowOf("questions.question1"),
    );
    expect(body.changes?.map((c) => c.field_id)).toEqual([
      "questions.question1.label",
      "questions.question1.text",
      "questions.question1.answer_type",
    ]);
  });

  it("基本と補足の指示は欄を空にする（行の無い節）", () => {
    const draft = {
      ...demoDraft(),
      sources: {
        "basic.target": "standard" as const,
        notes: "standard" as const,
      },
    };
    const rows = aiRowsOf([
      value("basic.target", "対象", "大腸がん"),
      value("notes", "補足の指示", "院内の決まり"),
    ]);
    expect(deletePatchOf(draft, rows[0]).body).toEqual({
      changes: [{ field_id: "basic.target", value: null }],
    });
    expect(deletePatchOf(draft, rows[1]).body).toEqual({
      changes: [{ field_id: "notes", value: "" }],
    });
  });

  it("引数の下書きは変えない", () => {
    const draft = demoDraft();
    const copy = structuredClone(draft);
    deletePatchOf(draft, rowOf("questions.question1"));
    expect(draft).toEqual(copy);
  });
});
