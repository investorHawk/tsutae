/**
 * P1 の自由記載の長さ。EntryCreate.free_text は Python の文字数（code point）で 2000 字まで。
 * native の maxLength は UTF-16 単位で数えるので付けず、送る前に検査して定型文で知らせる。
 * （このファイルに日本語を直書きしない。患者画面のアーキテクチャテストの対象になるため）
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { callsTo, mockPatientApi } from "./testing/api";
import { PID, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Today from "./Today";

const ENTRIES_URL = `/api/patient/${PID}/entries`;
// 患者画面のテストは文字列リテラルに ASCII 以外を書かない約束なので、コードポイントから作る
const EMOJI = String.fromCodePoint(0x1f600);

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function pasteFreeText(text: string) {
  const box = await screen.findByRole("textbox", {
    name: s("today.free_text_label"),
  });
  await userEvent.click(box);
  await userEvent.paste(text);
  return box;
}

function submitButton() {
  return screen.getByRole("button", { name: s("today.submit") });
}

describe("Today (P1): free text length", () => {
  it("the textarea has no native maxLength", async () => {
    mockPatientApi();
    renderPatient([{ path: "/today", element: <Today /> }], "/today");
    const box = await screen.findByRole("textbox", {
      name: s("today.free_text_label"),
    });
    expect(box).not.toHaveAttribute("maxlength");
  });

  it("2000 emoji (4000 UTF-16 units) are sent as is", async () => {
    const fetchMock = mockPatientApi();
    renderPatient([{ path: "/today", element: <Today /> }], "/today");
    const text = EMOJI.repeat(2000);
    const box = await pasteFreeText(text);
    expect(box).toHaveValue(text);
    await userEvent.click(submitButton());
    await screen.findByText(s("today.saved"));
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      { by_proxy: false, answers: [], free_text: text },
    ]);
  });

  it("2001 emoji: not sent, not cut, an approved message is shown", async () => {
    const fetchMock = mockPatientApi();
    renderPatient([{ path: "/today", element: <Today /> }], "/today");
    const text = EMOJI.repeat(2001);
    const box = await pasteFreeText(text);
    await userEvent.click(submitButton());
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(box).toHaveValue(text);
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([]);
    expect(screen.queryByText(s("today.saved"))).toBeNull();
  });
});
