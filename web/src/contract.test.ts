import { describe, expect, it } from "vitest";
import {
  ingestPortfolio,
  portfolioFile,
  sourceUrl,
  streamCouncil,
} from "./contract";
import { readFileSync } from "node:fs";

const encoder = new TextEncoder();
function stream(chunks: string[]) {
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
  );
}
describe("broker upload boundary", () => {
  it("converts the actual supplied broker snapshot using per-share entry cost", async () => {
    const snapshot = JSON.parse(
      readFileSync(
        new URL("../../data/portfolio.json", import.meta.url),
        "utf8",
      ),
    );
    const uploaded = new File([JSON.stringify(snapshot)], "portfolio.JSON");
    const output = JSON.parse(await (await ingestPortfolio(uploaded)).text());
    expect(output.holdings).toHaveLength(snapshot.positions.length);
    expect(output.holdings[0]).toEqual({
      ticker: snapshot.positions[0].symbol,
      shares: snapshot.positions[0].qty,
      cost_basis: snapshot.positions[0].avg_entry_price,
    });
  });
  it.each([
    ["portfolio.csv", "ticker,shares,cost_basis\nAAPL,2,100\n"],
    [
      "portfolio.json",
      '{"holdings":[{"ticker":"AAPL","shares":2,"cost_basis":100}]}',
    ],
    ["portfolio.json", '[{"ticker":"AAPL","shares":2,"cost_basis":100}]'],
  ])("preserves supported holdings in %s", async (name, contents) => {
    const uploaded = new File([contents], name);
    expect(await ingestPortfolio(uploaded)).toBe(uploaded);
  });
  it("rejects invalid JSON and malformed uploaded broker positions", async () => {
    await expect(
      ingestPortfolio(new File(["{"], "portfolio.json")),
    ).rejects.toThrow();
    await expect(
      ingestPortfolio(new File(['{"positions":[]}'], "portfolio.json")),
    ).rejects.toThrow("no positions");
  });
  it("rejects malformed broker positions", () => {
    expect(() =>
      portfolioFile({
        positions: [{ symbol: "X", qty: -1, avg_entry_price: 10 }],
      }),
    ).toThrow();
    expect(() => portfolioFile({ positions: [] })).toThrow();
  });
});
describe("source links", () => {
  it("renders only usable HTTP source links, never the server placeholder", () => {
    expect(sourceUrl("https://example.com/anchor-stub")).toBeUndefined();
    expect(sourceUrl("javascript:alert(1)")).toBeUndefined();
    expect(
      sourceUrl("https://www.berkshirehathaway.com/letters/letters.html"),
    ).toContain("berkshirehathaway.com");
  });
});
describe("POST SSE", () => {
  it("accepts all event types for the fifth configured worker", async () => {
    const prior = globalThis.fetch;
    globalThis.fetch = async () =>
      stream([
        'event: run.started\ndata: {"run_id":"five"}\n\n',
        'event: member.status\ndata: {"member":"dalio","status":"researching"}\n\n',
        'event: member.source\ndata: {"member":"dalio","title":"Report","url":"https://issuer.test"}\n\n',
        'event: member.verdict\ndata: {"member":"dalio","signal":"HOLD","confidence":0.5,"headline":"h","reasons":[],"sources":[],"tickers":[]}\n\n',
        'event: member.audio\ndata: {"member":"dalio","audio_url":"/api/voice/speak"}\n\n',
        'event: run.done\ndata: {"run_id":"five"}\n\n',
      ]);
    const received: string[] = [];
    try {
      await streamCouncil(
        "/api/council/run",
        {},
        new AbortController().signal,
        async (event) => {
          received.push(event.event);
        },
      );
    } finally {
      globalThis.fetch = prior;
    }
    expect(received).toEqual([
      "run.started",
      "member.status",
      "member.source",
      "member.verdict",
      "member.audio",
      "run.done",
    ]);
  });
  it("handles frames split across chunks and CRLF boundaries in order", async () => {
    const prior = globalThis.fetch;
    globalThis.fetch = async () =>
      stream([
        "event: run.started\r",
        '\ndata: {"run_id":"receipt"}\r\n\r',
        '\nevent: run.done\ndata: {"run_id":"receipt"}\n\n',
      ]);
    const received: string[] = [];
    try {
      await streamCouncil(
        "/api/council/run",
        {},
        new AbortController().signal,
        async (event) => {
          received.push(event.event);
        },
      );
    } finally {
      globalThis.fetch = prior;
    }
    expect(received).toEqual(["run.started", "run.done"]);
  });
  it("rejects an interrupted stream instead of claiming completion", async () => {
    const prior = globalThis.fetch;
    globalThis.fetch = async () =>
      stream(['event: run.started\ndata: {"run_id":"receipt"}\n\n']);
    try {
      await expect(
        streamCouncil(
          "/api/council/run",
          {},
          new AbortController().signal,
          async () => {},
        ),
      ).rejects.toThrow("ended early");
    } finally {
      globalThis.fetch = prior;
    }
  });
});
