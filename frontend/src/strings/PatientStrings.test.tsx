import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { callOf, jsonResponse, mockFetch } from "../test/fetchMock";
import { PATIENT_STRINGS_FIXTURE } from "../test/patientStringsFixture";
import { BUNDLED_STRINGS, REQUIRED_KEYS } from "./bundledStrings";
import {
  PatientStringsProvider,
  usePatientStrings,
  validatePatientStrings,
} from "./PatientStrings";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Show({ k }: { k: string }) {
  const { t } = usePatientStrings();
  return <p data-testid="out">[{t(k)}]</p>;
}

/** テストでは取り直しを待たない。 */
const NO_WAIT = [0, 0] as const;

function renderShow(k = "today.title") {
  return render(
    <PatientStringsProvider retryDelaysMs={NO_WAIT}>
      <Show k={k} />
    </PatientStringsProvider>,
  );
}

describe("同梱の定型文（bundledStrings）", () => {
  it("patient_strings.json の実物と同じ", () => {
    expect(BUNDLED_STRINGS).toEqual(PATIENT_STRINGS_FIXTURE);
    expect(REQUIRED_KEYS).toEqual(Object.keys(PATIENT_STRINGS_FIXTURE));
  });
});

describe("validatePatientStrings", () => {
  it("必要なキーが全て文字列なら、文字列の値だけを返す", () => {
    const data = { ...PATIENT_STRINGS_FIXTURE, extra: "x", num: 1 };
    const result = validatePatientStrings(data);
    expect(result).toEqual({ ...PATIENT_STRINGS_FIXTURE, extra: "x" });
    expect(Object.isFrozen(result)).toBe(true);
  });

  it.each([
    ["配列", ["today.title"]],
    ["null", null],
    ["文字列", "x"],
    ["キーが欠ける", { "app.title": "x" }],
    ["文字列でない値", { ...PATIENT_STRINGS_FIXTURE, "today.title": 1 }],
    ["空文字", { ...PATIENT_STRINGS_FIXTURE, "today.submit": "" }],
  ])("%s は null", (_label, data) => {
    expect(validatePatientStrings(data)).toBeNull();
  });
});

describe("PatientStringsProvider", () => {
  it("GET /api/patient/strings を読み、t(key) でサーバーの定型文を返す", async () => {
    const served = { ...PATIENT_STRINGS_FIXTURE, "today.title": "served" };
    const fetchMock = mockFetch(() => jsonResponse(served));
    renderShow();
    expect(await screen.findByTestId("out")).toHaveTextContent("[served]");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(callOf(fetchMock).url).toBe("/api/patient/strings");
  });

  it("読み込み中は何も出さない", async () => {
    let resolve: (r: Response) => void = () => {};
    mockFetch(
      () =>
        new Promise<Response>((r) => {
          resolve = r;
        }),
    );
    const { container } = renderShow();
    expect(container).toBeEmptyDOMElement();
    resolve(jsonResponse(PATIENT_STRINGS_FIXTURE));
    expect(await screen.findByTestId("out")).toHaveTextContent("[今日の記録]");
  });

  it("未知のキーは空文字を返し console.warn する", async () => {
    mockFetch(() => jsonResponse(PATIENT_STRINGS_FIXTURE));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderShow("no.such.key");
    expect(await screen.findByTestId("out")).toHaveTextContent("[]");
    expect(warn).toHaveBeenCalled();
    expect(String(warn.mock.calls[0]?.[0])).toContain("no.such.key");
  });

  it("失敗したら取り直し、成功すればサーバーの定型文を使う", async () => {
    const served = { ...PATIENT_STRINGS_FIXTURE, "today.title": "served" };
    let calls = 0;
    const fetchMock = mockFetch(() => {
      calls += 1;
      return calls === 1
        ? jsonResponse({ error: "boom" }, 500)
        : jsonResponse(served);
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderShow();
    expect(await screen.findByTestId("out")).toHaveTextContent("[served]");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["500", () => jsonResponse({ error: "boom" }, 500)],
    ["通信エラー", () => Promise.reject(new TypeError("Failed to fetch"))],
  ])(
    "取り直しても失敗（%s）なら同梱の定型文で描く（空白にしない）",
    async (_label, reply) => {
      const fetchMock = mockFetch(reply);
      const error = vi.spyOn(console, "error").mockImplementation(() => {});
      renderShow();
      expect(await screen.findByTestId("out")).toHaveTextContent(
        "[今日の記録]",
      );
      expect(fetchMock).toHaveBeenCalledTimes(1 + NO_WAIT.length);
      expect(error).toHaveBeenCalled();
    },
  );

  it.each([
    ["オブジェクトでない", ["today.title"]],
    ["キーが欠ける", { "app.title": "x" }],
    ["文字列でない値", { ...PATIENT_STRINGS_FIXTURE, "today.title": 1 }],
  ])(
    "本文が不正（%s）なら同梱の定型文で描く（見出しを空にしない）",
    async (_label, body) => {
      mockFetch(() => jsonResponse(body));
      vi.spyOn(console, "error").mockImplementation(() => {});
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
      renderShow();
      expect(await screen.findByTestId("out")).toHaveTextContent(
        "[今日の記録]",
      );
      expect(warn).not.toHaveBeenCalled();
    },
  );

  it("Provider の外で usePatientStrings を使うと例外", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Show k="today.title" />)).toThrow(
      /PatientStringsProvider/,
    );
  });
});
