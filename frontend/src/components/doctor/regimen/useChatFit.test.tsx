/**
 * チャットの枠の高さ: 画面の下端までに収める。jsdom は配置を計算しないので、
 * getBoundingClientRect と innerHeight を偽装して CSS 変数を確かめる。
 */
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CHAT_STICKY_TOP, chatHeightOf, useChatFit } from "./useChatFit";

function Box({ marker }: { marker?: string }) {
  const ref = useChatFit();
  return <aside ref={ref} data-testid="chat" data-marker={marker} />;
}

let top = 200;
let frames: FrameRequestCallback[] = [];

function chatHeight(el: HTMLElement): string {
  return el.style.getPropertyValue("--rf-chat-h");
}

function runFrames() {
  const pending = frames;
  frames = [];
  pending.forEach((run) => run(0));
}

beforeEach(() => {
  top = 200;
  frames = [];
  vi.stubGlobal("innerHeight", 800);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    () => ({ top }) as DOMRect,
  );
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((run) => {
    frames.push(run);
    return frames.length;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
    frames.splice(id - 1, 1);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("chatHeightOf", () => {
  it("枠の上端から画面の下端まで（下の余白 24px を除く）", () => {
    expect(chatHeightOf(200, 800)).toBe(576);
  });

  it("上端が sticky の位置より上なら sticky の位置で計算する", () => {
    expect(chatHeightOf(-300, 800)).toBe(800 - CHAT_STICKY_TOP - 24);
    expect(chatHeightOf(CHAT_STICKY_TOP, 800)).toBe(736);
  });

  it("枠が画面より下にあっても負にしない（CSS の min-height に任せる）", () => {
    expect(chatHeightOf(2000, 800)).toBe(0);
  });
});

describe("useChatFit", () => {
  it("描いたときに高さと sticky の位置を変数に入れる", () => {
    const { getByTestId } = render(<Box />);
    const chat = getByTestId("chat");
    expect(chatHeight(chat)).toBe("576px");
    expect(chat.style.getPropertyValue("--rf-chat-top")).toBe(
      `${CHAT_STICKY_TOP}px`,
    );
  });

  it("scroll で計算し直す（passive。枠が上に貼りついた後は最大の高さ）", () => {
    const add = vi.spyOn(window, "addEventListener");
    const { getByTestId } = render(<Box />);
    expect(add).toHaveBeenCalledWith("scroll", expect.any(Function), {
      passive: true,
    });
    top = 40;
    window.dispatchEvent(new Event("scroll"));
    expect(chatHeight(getByTestId("chat"))).toBe("576px");
    runFrames();
    expect(chatHeight(getByTestId("chat"))).toBe("736px");
  });

  it("1回の描画の枠で何度 scroll が来ても1回だけ計算する", () => {
    render(<Box />);
    window.dispatchEvent(new Event("scroll"));
    window.dispatchEvent(new Event("scroll"));
    window.dispatchEvent(new Event("resize"));
    expect(frames).toHaveLength(1);
    runFrames();
    window.dispatchEvent(new Event("scroll"));
    expect(frames).toHaveLength(1);
  });

  it("resize で計算し直す", () => {
    const { getByTestId } = render(<Box />);
    vi.stubGlobal("innerHeight", 600);
    window.dispatchEvent(new Event("resize"));
    runFrames();
    expect(chatHeight(getByTestId("chat"))).toBe("376px");
  });

  it("描き直し（下書きが変わった・上に帯が出た）で計算し直す", () => {
    const { getByTestId, rerender } = render(<Box marker="a" />);
    top = 300;
    rerender(<Box marker="b" />);
    expect(chatHeight(getByTestId("chat"))).toBe("476px");
  });

  it("外したら聞くのをやめ、待っている計算も取り消す", () => {
    const remove = vi.spyOn(window, "removeEventListener");
    const { getByTestId, unmount } = render(<Box />);
    const chat = getByTestId("chat");
    window.dispatchEvent(new Event("scroll"));
    expect(frames).toHaveLength(1);
    unmount();
    expect(frames).toHaveLength(0);
    expect(remove).toHaveBeenCalledWith("scroll", expect.any(Function));
    expect(remove).toHaveBeenCalledWith("resize", expect.any(Function));
    top = 40;
    window.dispatchEvent(new Event("resize"));
    expect(frames).toHaveLength(0);
    expect(chatHeight(chat)).toBe("576px");
  });
});
