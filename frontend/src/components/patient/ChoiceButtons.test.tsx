/** 選択ボタン（P2-1）。「つらい」を選んだときは「ある」と違う見た目にする（class で見分ける）。 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { THREE_LEVEL_VALUES } from "../../api/types";
import { s, STRINGS } from "../../pages/patient/testing/fixtures";
import { StaticPatientStringsProvider } from "../../strings/PatientStrings";
import ChoiceButtons from "./ChoiceButtons";

function renderChoices(selected: "none" | "present" | "hard" | undefined) {
  return render(
    <StaticPatientStringsProvider strings={STRINGS}>
      <ChoiceButtons
        values={THREE_LEVEL_VALUES}
        selected={selected}
        onSelect={vi.fn()}
      />
    </StaticPatientStringsProvider>,
  );
}

describe("ChoiceButtons", () => {
  it("each button has a class for its value", () => {
    renderChoices(undefined);
    for (const value of THREE_LEVEL_VALUES) {
      expect(
        screen.getByRole("button", { name: s(`answer.${value}`) }),
      ).toHaveClass("p-choice", `p-choice--${value}`);
    }
  });

  it.each(THREE_LEVEL_VALUES)("only %s is pressed", (value) => {
    renderChoices(value);
    for (const other of THREE_LEVEL_VALUES) {
      expect(
        screen.getByRole("button", { name: s(`answer.${other}`) }),
      ).toHaveAttribute("aria-pressed", String(other === value));
    }
  });
});
