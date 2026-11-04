import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  bodiesOf,
  mockApi,
  renderRoute,
} from "../../components/doctor/testing";
import { jsonResponse } from "../../test/fetchMock";
import Login from "./Login";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderLogin(state?: unknown) {
  return renderRoute("/doctor/login", "/doctor/login", <Login />, state);
}

async function submit(password: string) {
  await userEvent.type(screen.getByLabelText("パスワード"), password);
  await userEvent.click(screen.getByRole("button", { name: "ログイン" }));
}

describe("Login", () => {
  it("開いただけでは API を呼ばず、空のパスワードでは押せない", () => {
    const fetchMock = mockApi({});
    renderLogin();
    expect(
      screen.getByRole("heading", { level: 1, name: "ログイン" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ログイン" })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("アプリ名と、院内の医師用の画面である一文を出す（D1-1）", () => {
    mockApi({});
    renderLogin();
    expect(screen.getByText("つたえ")).toBeInTheDocument();
    expect(screen.getByText(/院内の医師用の画面です/)).toBeInTheDocument();
  });

  it("パスワードを POST して /doctor へ", async () => {
    const fetchMock = mockApi({ "POST /api/doctor/login": { ok: true } });
    renderLogin();
    await submit("demo-pass");
    expect(bodiesOf(fetchMock, "POST /api/doctor/login")).toEqual([
      { password: "demo-pass" },
    ]);
    expect(await screen.findByTestId("where")).toHaveTextContent(/^\/doctor$/);
  });

  it("state.from があればそこへ戻る", async () => {
    mockApi({ "POST /api/doctor/login": { ok: true } });
    renderLogin({ from: "/doctor/settings" });
    await submit("demo-pass");
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent(
        /^\/doctor\/settings$/,
      ),
    );
  });

  it.each(["/today", "https://example.invalid/doctor", "/doctor/login"])(
    "state.from が %s なら /doctor へ",
    async (from) => {
      mockApi({ "POST /api/doctor/login": { ok: true } });
      renderLogin({ from });
      await submit("demo-pass");
      await waitFor(() =>
        expect(screen.getByTestId("where")).toHaveTextContent(/^\/doctor$/),
      );
    },
  );

  it("401 なら「パスワードが違います」でこの画面に残る", async () => {
    mockApi({
      "POST /api/doctor/login": () =>
        jsonResponse({ error: "bad_password" }, 401),
    });
    renderLogin();
    await submit("wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "パスワードが違います",
    );
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/doctor\/login$/);
    expect(screen.getByRole("button", { name: "ログイン" })).toBeEnabled();
  });

  it("その他の失敗は code を出す", async () => {
    mockApi({
      "POST /api/doctor/login": () =>
        jsonResponse({ error: "server_error" }, 500),
    });
    renderLogin();
    await submit("demo-pass");
    expect(await screen.findByRole("alert")).toHaveTextContent("server_error");
  });

  it.each([
    ["{ok:false}", { ok: false }],
    ["本文が空", {}],
  ])("200 でも %s ならログインできたとしない", async (_label, body) => {
    mockApi({ "POST /api/doctor/login": body });
    renderLogin();
    await submit("demo-pass");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/doctor\/login$/);
  });
});
