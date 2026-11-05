/**
 * NotRegistered: the not-registered notice with the number field.
 * Expected text comes from patient_strings.json (no literal Japanese in this file).
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, loadPid, savePid } from "../../patient/pid";
import { reloadPage } from "../../patient/reload";
import { StaticPatientStringsProvider } from "../../strings/PatientStrings";
import { callOf, jsonResponse, mockFetch } from "../../test/fetchMock";
import { STRINGS, s } from "../../pages/patient/testing/fixtures";
import NotRegistered from "./NotRegistered";

vi.mock("../../patient/reload", () => ({ reloadPage: vi.fn() }));

const PID = "P-AB12CD34";
const OLD_PID = "P-OLD00001";
// Full-width "p-ab12cd34". Tests keep non-ASCII out of string literals.
const FULLWIDTH_PID = String.fromCodePoint(
  0xff50,
  0xff0d,
  0xff41,
  0xff42,
  0xff11,
  0xff12,
  0xff43,
  0xff44,
  0xff13,
  0xff14,
);

function renderPanel(onRegistered?: (pid: string) => void) {
  return render(
    <StaticPatientStringsProvider strings={STRINGS}>
      <NotRegistered onRegistered={onRegistered} />
    </StaticPatientStringsProvider>,
  );
}

function field() {
  return screen.getByRole("textbox", { name: s("register.number_label") });
}

function submit() {
  return screen.getByRole("button", { name: s("register.number_submit") });
}

async function enter(text: string) {
  await userEvent.type(field(), text);
  await userEvent.click(submit());
}

beforeEach(() => {
  clearPid();
  vi.mocked(reloadPage).mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NotRegistered", () => {
  it("shows the notice, the labelled field and the button", () => {
    mockFetch(() => jsonResponse({ ok: true }));
    renderPanel();
    expect(screen.getByRole("alert")).toHaveTextContent(
      s("error.not_registered"),
    );
    expect(field()).toHaveAttribute(
      "placeholder",
      s("register.number_placeholder"),
    );
    expect(submit()).toHaveClass("p-button--primary");
  });

  it("the field does not fight with typing on a phone", () => {
    mockFetch(() => jsonResponse({ ok: true }));
    renderPanel();
    expect(field()).toHaveAttribute("autocapitalize", "characters");
    expect(field()).toHaveAttribute("autocomplete", "off");
    expect(field()).toHaveAttribute("autocorrect", "off");
    expect(field()).toHaveAttribute("spellcheck", "false");
  });

  it("saves the pid, registers, then reloads the page", async () => {
    let savedAtRequest: string | null = null;
    const fetchMock = mockFetch(() => {
      savedAtRequest = loadPid();
      return jsonResponse({ ok: true });
    });
    renderPanel();
    await enter(PID);
    await waitFor(() => expect(reloadPage).toHaveBeenCalledTimes(1));
    const call = callOf(fetchMock);
    expect(call.method).toBe("POST");
    expect(call.url).toBe("/api/patient/register");
    expect(call.body).toEqual({ pid: PID });
    expect(savedAtRequest).toBe(PID);
    expect(loadPid()).toBe(PID);
  });

  it.each([
    ["lower case", "p-ab12cd34"],
    ["surrounding spaces", "  P-AB12CD34  "],
    ["no prefix", "ab12cd34"],
    ["full width", FULLWIDTH_PID],
  ])("normalizes the input: %s", async (_label, text) => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    renderPanel();
    await enter(text);
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
    expect(callOf(fetchMock).body).toEqual({ pid: PID });
    expect(loadPid()).toBe(PID);
  });

  it("the Enter key sends too", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    renderPanel();
    await userEvent.type(field(), `${PID}{Enter}`);
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["empty", ""],
    ["too short", "AB12CD3"],
    ["symbols", "AB12CD3!"],
    ["path", "P-DEMO0001/../x"],
  ])(
    "a number of the wrong form: register.number_invalid, no request (%s)",
    async (_label, text) => {
      const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
      renderPanel();
      if (text !== "") {
        await userEvent.type(field(), text);
      }
      await userEvent.click(submit());
      expect(
        await screen.findByText(s("register.number_invalid")),
      ).toBeInTheDocument();
      expect(fetchMock).not.toHaveBeenCalled();
      expect(loadPid()).toBeNull();
      expect(field()).toHaveAttribute("aria-invalid", "true");
    },
  );

  it.each([400, 404, 422])(
    "%i: register.number_invalid, the pid is put back and the input stays",
    async (status) => {
      savePid(OLD_PID);
      mockFetch(() => jsonResponse({ error: "unknown_patient" }, status));
      renderPanel();
      await enter(PID);
      expect(
        await screen.findByText(s("register.number_invalid")),
      ).toBeInTheDocument();
      expect(loadPid()).toBe(OLD_PID);
      expect(field()).toHaveValue(PID);
      expect(submit()).toBeEnabled();
      expect(reloadPage).not.toHaveBeenCalled();
    },
  );

  it("429: error.too_many_attempts and nothing stays saved", async () => {
    mockFetch(() => jsonResponse({ error: "too_many_attempts" }, 429));
    renderPanel();
    await enter(PID);
    expect(
      await screen.findByText(s("error.too_many_attempts")),
    ).toBeInTheDocument();
    expect(loadPid()).toBeNull();
    expect(reloadPage).not.toHaveBeenCalled();
    expect(field()).not.toHaveAttribute("aria-invalid", "true");
  });

  it("500: error.generic and it can be sent again", async () => {
    let fail = true;
    mockFetch(() =>
      fail ? jsonResponse({ error: "boom" }, 500) : jsonResponse({ ok: true }),
    );
    renderPanel();
    await enter(PID);
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(loadPid()).toBeNull();
    fail = false;
    await userEvent.click(submit());
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
    expect(screen.queryByText(s("error.generic"))).toBeNull();
  });

  it("a network failure: error.generic", async () => {
    mockFetch(() => Promise.reject(new TypeError("offline")));
    renderPanel();
    await enter(PID);
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(loadPid()).toBeNull();
  });

  it("storage unavailable: error.generic and no request", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    renderPanel();
    await enter(PID);
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(submit()).toBeEnabled();
  });

  it("the button is off while sending (no second request)", async () => {
    let release: (value: Response) => void = () => undefined;
    const fetchMock = mockFetch(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    renderPanel();
    await enter(PID);
    expect(submit()).toBeDisabled();
    expect(field()).toBeDisabled();
    await userEvent.click(submit());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    release(jsonResponse({ ok: true }));
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
  });

  it("with onRegistered: hands over the saved pid and does not reload", async () => {
    mockFetch(() => jsonResponse({ ok: true }));
    const onRegistered = vi.fn();
    renderPanel(onRegistered);
    await enter("ab12cd34");
    await waitFor(() => expect(onRegistered).toHaveBeenCalledWith(PID));
    expect(reloadPage).not.toHaveBeenCalled();
  });
});
