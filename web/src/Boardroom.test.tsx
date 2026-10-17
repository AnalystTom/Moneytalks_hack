import { Children, isValidElement } from "react";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import Boardroom from "./Boardroom";
import { members } from "./contract";
import type { Member, Verdict } from "./contract";

type ElementProps = {
  className?: string;
  children?: ReactNode;
  onClick?: () => void;
};
function buttons(node: ReactNode): ElementProps[] {
  return Children.toArray(node).flatMap((child) => {
    if (!isValidElement<ElementProps>(child)) return [];
    return [
      ...(child.type === "button" ? [child.props] : []),
      ...buttons(child.props.children),
    ];
  });
}
const verdict = (
  member: Member,
  signal: Verdict["signal"],
  headline: string,
): Verdict => ({
  member,
  signal,
  headline,
  confidence: 0.8,
  reasons: [],
  sources: [],
  tickers: [],
});

describe("cartoon boardroom", () => {
  it("renders all five empty seats with pending icons and the generated assets", () => {
    const html = renderToStaticMarkup(
      <Boardroom
        statuses={{}}
        verdicts={{}}
        sources={{}}
        onSelect={() => {}}
      />,
    );
    expect(html.match(/class="speech-bubble"/g)).toHaveLength(5);
    expect(html.match(/aria-label="Pending"/g)).toHaveLength(5);
    expect(html.match(/No verdict yet\./g)).toHaveLength(10);
    for (const member of Object.keys(members)) {
      expect(html).toContain(`/portraits/${member}.png`);
      const asset = new URL(
        `../public/portraits/${member}.png`,
        import.meta.url,
      );
      expect(existsSync(asset)).toBe(true);
      const png = readFileSync(asset);
      expect(png.subarray(1, 4).toString()).toBe("PNG");
      expect(png[25]).toBe(6);
    }
    expect(html.indexOf("council-seat leopold")).toBeLessThan(
      html.indexOf("council-seat buffett"),
    );
    expect(html.indexOf("council-seat buffett")).toBeLessThan(
      html.indexOf("council-seat dalio"),
    );
  });

  it("shortens long streamed lines and opens the matching member details", () => {
    const onSelect = vi.fn();
    const longLine =
      "A long returned line with risk and allocation context. ".repeat(40);
    const tree = Boardroom({
      active: "burry",
      statuses: {},
      sources: {},
      onSelect,
      verdicts: {
        buffett: verdict("buffett", "HOLD", longLine),
        leopold: verdict("leopold", "BUY", longLine),
        burry: verdict("burry", "SELL", longLine),
        cramer: verdict("cramer", "HOLD", longLine),
      },
    });
    const html = renderToStaticMarkup(tree);
    expect(html).not.toContain(longLine);
    expect(
      html.match(/A long returned line with risk and allocation context\./g),
    ).toHaveLength(8);
    for (const signal of ["BUY", "HOLD", "SELL"])
      expect(html).toContain(`aria-label="${signal}"`);
    const bubbles = buttons(tree).filter(
      (button) => button.className === "speech-bubble",
    );
    bubbles.forEach((bubble) => bubble.onClick!());
    expect(onSelect.mock.calls.flat()).toEqual([
      "leopold",
      "burry",
      "buffett",
      "dalio",
      "cramer",
    ]);
  });

  it("renders returned status, valid source counts, and Warren’s final summary", () => {
    const html = renderToStaticMarkup(
      <Boardroom
        statuses={{ leopold: "researching" }}
        verdicts={{ buffett: verdict("buffett", "BUY", "Earlier verdict") }}
        sources={{
          burry: [
            { title: "SEC", url: "https://www.sec.gov/" },
            { title: "Unavailable", url: "https://example.com/stub" },
          ],
        }}
        chair={{
          overall_signal: "HOLD",
          summary: "Returned final summary",
          consensus: "Returned consensus",
          dissent: [],
        }}
        onSelect={() => {}}
      />,
    );
    expect(html).toContain("researching");
    expect(html).toContain("Reviewing 1 source…");
    expect(html).toContain("Returned final summary");
    expect(html).toContain("Final word");
    expect(html).not.toContain("Earlier verdict");
  });
});
