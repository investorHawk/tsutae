/**
 * 回答の表（これまでの記録の詳しい表示と、記録した後の確認で同じ部品）。
 * 列は なし／ある／つらい、行は短い症状名。選んだ欄だけに答えの文字を出す。
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { THREE_LEVEL_VALUES } from "../../api/types";
import { s, STRINGS } from "../../pages/patient/testing/fixtures";
import { StaticPatientStringsProvider } from "../../strings/PatientStrings";
import AnswerTable from "./AnswerTable";
import type { SummaryAnswer } from "./entrySummary";

function renderTable(answers: readonly SummaryAnswer[]) {
  return render(
    <StaticPatientStringsProvider strings={STRINGS}>
      <AnswerTable answers={answers} />
    </StaticPatientStringsProvider>,
  );
}

function answer(
  questionKey: string,
  value: SummaryAnswer["value"],
  extra: Partial<SummaryAnswer> = {},
): SummaryAnswer {
  return { questionKey, value, questionText: "question text", ...extra };
}

function temperatureText(value: string): string {
  return `${s("answer.measured")} ${s("history.temperature_value").replace("{value}", value)}`;
}

describe("AnswerTable", () => {
  it("has the three answers as column headers", () => {
    renderTable([answer("numbness", "present")]);
    expect(
      screen.getAllByRole("columnheader").map((th) => th.textContent),
    ).toEqual(THREE_LEVEL_VALUES.map((v) => s(`answer.${v}`)));
  });

  it("one row per answer, named by the short symptom name", () => {
    renderTable([
      answer("numbness", "present"),
      answer("diarrhea", "none"),
      answer("stomatitis", "hard"),
    ]);
    expect(
      screen.getAllByRole("rowheader").map((th) => th.textContent),
    ).toEqual([
      s("symptom.numbness"),
      s("symptom.diarrhea"),
      s("symptom.stomatitis"),
    ]);
  });

  it.each(THREE_LEVEL_VALUES)(
    "%s: only the chosen cell has text (read as 'symptom: answer')",
    (value) => {
      renderTable([answer("numbness", value)]);
      const label = s("symptom.numbness");
      const row = screen.getByRole("row", {
        name: `${label} ${s(`answer.${value}`)}`,
      });
      const cells = within(row).getAllByRole("cell");
      expect(cells).toHaveLength(3);
      THREE_LEVEL_VALUES.forEach((v, i) => {
        if (v === value) {
          expect(cells[i]).toHaveTextContent(s(`answer.${v}`));
          expect(cells[i]).toHaveClass("p-answer-cell--chosen");
          expect(within(cells[i]!).getByText(s(`answer.${v}`)).tagName).toBe(
            "STRONG",
          );
        } else {
          expect(cells[i]).toHaveTextContent(/^$/);
          expect(cells[i]).not.toHaveClass("p-answer-cell--chosen");
        }
      });
    },
  );

  it("temperature: one cell across the three columns", () => {
    renderTable([answer("fever", "measured", { temperature: 36.8 })]);
    const row = screen.getByRole("row", {
      name: `${s("symptom.fever")} ${temperatureText("36.8")}`,
    });
    const cells = within(row).getAllByRole("cell");
    expect(cells).toHaveLength(1);
    expect(cells[0]).toHaveAttribute("colspan", "3");
  });

  it("not measured, and measured without a number", () => {
    renderTable([
      answer("fever", "not_measured"),
      answer("fever_2", "measured", { questionText: "second" }),
    ]);
    expect(
      screen.getByRole("row", {
        name: `${s("symptom.fever")} ${s("answer.not_measured")}`,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("row", { name: `second ${s("answer.measured")}` }),
    ).toBeInTheDocument();
  });

  it("only temperature: no column headers", () => {
    renderTable([answer("fever", "not_measured")]);
    expect(screen.queryAllByRole("columnheader")).toHaveLength(0);
  });

  it("an unknown key uses the question text, then history.previous_question", () => {
    renderTable([
      answer("new_question", "hard", { questionText: "new question text" }),
      answer("old_question", "present", { questionText: null }),
    ]);
    expect(
      screen.getAllByRole("rowheader").map((th) => th.textContent),
    ).toEqual(["new question text", s("history.previous_question")]);
  });

  it("a three-level value on the temperature question is still shown", () => {
    renderTable([answer("fever", "hard")]);
    expect(
      screen.getByRole("row", {
        name: `${s("symptom.fever")} ${s("answer.hard")}`,
      }),
    ).toBeInTheDocument();
  });
});
