/**
 * 選択ボタン。何も選んでいない質問は全てのボタンを薄い橙にして入力を促す
 * （p-choices--unanswered）。選んだら、選んだボタンはどの答えでも同じ青（aria-pressed）、
 * 他は白。答えごとに見た目を変えていた P2-1 はやめた。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FEVER_VALUES, THREE_LEVEL_VALUES } from "../../api/types";
import type { AnswerValue } from "../../api/types";
import { s, STRINGS } from "../../pages/patient/testing/fixtures";
import { StaticPatientStringsProvider } from "../../strings/PatientStrings";
import ChoiceButtons from "./ChoiceButtons";

function renderChoices(
  selected: AnswerValue | undefined,
  values: readonly AnswerValue[] = THREE_LEVEL_VALUES,
) {
  return render(
    <StaticPatientStringsProvider strings={STRINGS}>
      <ChoiceButtons values={values} selected={selected} onSelect={vi.fn()} />
    </StaticPatientStringsProvider>,
  );
}

function buttonOf(value: AnswerValue): HTMLElement {
  return screen.getByRole("button", { name: s(`answer.${value}`) });
}

describe("ChoiceButtons", () => {
  it("nothing chosen: the group is marked unanswered and nothing is pressed", () => {
    const { container } = renderChoices(undefined);
    expect(container.querySelector(".p-choices")).toHaveClass(
      "p-choices--unanswered",
    );
    for (const value of THREE_LEVEL_VALUES) {
      expect(buttonOf(value)).toHaveAttribute("aria-pressed", "false");
    }
  });

  it("the temperature choices are also unanswered until one is chosen", () => {
    const { container } = renderChoices(undefined, FEVER_VALUES);
    expect(container.querySelector(".p-choices")).toHaveClass(
      "p-choices--unanswered",
    );
  });

  it.each(THREE_LEVEL_VALUES)(
    "%s chosen: only it is pressed, the group is answered",
    (value) => {
      const { container } = renderChoices(value);
      expect(container.querySelector(".p-choices")).not.toHaveClass(
        "p-choices--unanswered",
      );
      for (const other of THREE_LEVEL_VALUES) {
        expect(buttonOf(other)).toHaveAttribute(
          "aria-pressed",
          String(other === value),
        );
      }
    },
  );

  it("every answer has the same class (no look per answer)", () => {
    renderChoices("hard");
    for (const value of THREE_LEVEL_VALUES) {
      expect(buttonOf(value).className).toBe("p-choice");
    }
  });
});
