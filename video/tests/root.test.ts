import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { Root } from "../src/Root";

interface CompositionProps {
  id: string;
  defaultProps: { bgm: boolean };
}

/** Root が返す Fragment の子（Composition の要素）。描画はしない */
const compositions = (): CompositionProps[] => {
  const fragment = Root({}) as ReactElement<{
    children: ReactElement<CompositionProps>[];
  }>;
  return fragment.props.children.map((c) => c.props);
};

describe("Root の Composition", () => {
  it("字幕だけの 3 案（DemoA / DemoB / DemoC）だけを並べる", () => {
    expect(compositions().map((c) => c.id)).toEqual([
      "DemoA",
      "DemoB",
      "DemoC",
    ]);
  });

  it("BGM を鳴らすのは DemoB だけ", () => {
    expect(compositions().map((c) => [c.id, c.defaultProps.bgm])).toEqual([
      ["DemoA", false],
      ["DemoB", true],
      ["DemoC", false],
    ]);
  });
});
