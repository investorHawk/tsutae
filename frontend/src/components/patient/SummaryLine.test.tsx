/**
 * これまでの記録の一行の要約（タグの並び）。見た目は症状名だけ（ある・つらいは塗りと
 * 枠で分ける。印は付けない）、読み上げは「しびれ つらい」と答えまで読む。
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { s, STRINGS } from "../../pages/patient/testing/fixtures";
import { spokenText, visibleText } from "../../pages/patient/testing/text";
import { StaticPatientStringsProvider } from "../../strings/PatientStrings";
import { summarizeEntry, type SummarySource } from "./entrySummary";
import SummaryLine from "./SummaryLine";

function renderLine(source: SummarySource): HTMLElement {
  const { container } = render(
    <StaticPatientStringsProvider strings={STRINGS}>
      <SummaryLine items={summarizeEntry(source)} />
    </StaticPatientStringsProvider>,
  );
  const line = container.querySelector<HTMLElement>(".p-tags");
  if (!line) {
    throw new Error("p-tags is missing");
  }
  return line;
}

function tagsOf(line: HTMLElement): HTMLElement[] {
  return Array.from(line.querySelectorAll<HTMLElement>(".p-tag"));
}

function temperature(value: string): string {
  return s("history.temperature_value").replace("{value}", value);
}

const SOURCE: SummarySource = {
  tooSick: false,
  answers: [
    { questionKey: "numbness", value: "hard", questionText: "q1" },
    { questionKey: "diarrhea", value: "present", questionText: "q2" },
    { questionKey: "stomatitis", value: "none", questionText: "q3" },
    {
      questionKey: "fever",
      value: "measured",
      temperature: 37.2,
      questionText: "q5",
    },
  ],
  freeText: "abc",
  byProxy: true,
};

describe("SummaryLine (tags)", () => {
  it("one tag per item; none is not a tag", () => {
    const tags = tagsOf(renderLine(SOURCE));
    expect(tags.map(visibleText)).toEqual([
      s("symptom.numbness"),
      s("symptom.diarrhea"),
      temperature("37.2"),
      s("history.free_text"),
      s("history.proxy_short"),
    ]);
    expect(renderLine(SOURCE).textContent).not.toContain(
      s("symptom.stomatitis"),
    );
  });

  it("present: the symptom name only (light blue), read with the answer", () => {
    const tag = tagsOf(renderLine(SOURCE))[1]!;
    expect(tag).toHaveClass("p-tag", "p-tag--present");
    expect(visibleText(tag)).toBe(s("symptom.diarrhea"));
    expect(spokenText(tag)).toBe(
      `${s("symptom.diarrhea")} ${s("answer.present")}`,
    );
  });

  it("hard: the symptom name only, no mark (dark navy), read with the answer", () => {
    const tag = tagsOf(renderLine(SOURCE))[0]!;
    expect(tag).toHaveClass("p-tag", "p-tag--hard");
    expect(tag.querySelector(".p-tag-mark")).toBeNull();
    expect(visibleText(tag)).toBe(s("symptom.numbness"));
    expect(spokenText(tag)).toBe(
      `${s("symptom.numbness")} ${s("answer.hard")}`,
    );
  });

  it("temperature, free text and proxy are neutral tags", () => {
    const [, , fever, free, proxy] = tagsOf(renderLine(SOURCE));
    for (const tag of [fever!, free!, proxy!]) {
      expect(tag).toHaveClass("p-tag", "p-tag--neutral");
      expect(tag).not.toHaveClass("p-tag--present");
      expect(tag).not.toHaveClass("p-tag--hard");
    }
    expect(spokenText(fever!)).toBe(
      `${s("symptom.fever")} ${temperature("37.2")}`,
    );
    expect(spokenText(free!)).toBe(
      `${s("history.free_text")} ${s("history.free_text_present")}`,
    );
    expect(spokenText(proxy!)).toBe(s("history.proxy"));
  });

  it("too_sick is a neutral tag", () => {
    const tags = tagsOf(
      renderLine({ tooSick: true, answers: [], freeText: null }),
    );
    expect(tags).toHaveLength(1);
    expect(tags[0]).toHaveClass("p-tag--neutral");
    expect(spokenText(tags[0]!)).toBe(s("history.too_sick"));
  });

  it("all none: history.all_none as text, not a tag", () => {
    const line = renderLine({
      tooSick: false,
      answers: [{ questionKey: "diarrhea", value: "none", questionText: null }],
      freeText: null,
    });
    expect(tagsOf(line)).toHaveLength(0);
    expect(line).toHaveTextContent(s("history.all_none"));
  });

  it("the whole line reads with hidden separators between tags", () => {
    const line = renderLine({ ...SOURCE, freeText: null, byProxy: false });
    const sep = s("history.separator");
    expect(spokenText(line)).toBe(
      [
        `${s("symptom.numbness")} ${s("answer.hard")}`,
        `${s("symptom.diarrhea")} ${s("answer.present")}`,
        `${s("symptom.fever")} ${temperature("37.2")}`,
      ].join(sep),
    );
    const seps = Array.from(line.children).filter(
      (el) => !el.classList.contains("p-tag"),
    );
    expect(seps).toHaveLength(2);
    for (const el of seps) {
      expect(el).toHaveClass("visually-hidden");
      expect(el).toHaveTextContent(sep);
    }
  });

  it("an unknown question key: the question text is the tag", () => {
    const tags = tagsOf(
      renderLine({
        tooSick: false,
        answers: [
          {
            questionKey: "new_question",
            value: "present",
            questionText: "new question text",
          },
        ],
        freeText: null,
      }),
    );
    expect(visibleText(tags[0]!)).toBe("new question text");
  });
});
