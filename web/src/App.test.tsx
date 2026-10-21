import { readFileSync } from "node:fs";
import { Children, isValidElement } from "react";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import ProfileModal from "./ProfileModal";
import VoiceInput from "./VoiceInput";
import ReadAloud from "./ReadAloud";
import { SpeechPlayback } from "./speech";
import { streamCouncil } from "./contract";
import type { Verdict } from "./contract";

const hooks = vi.hoisted(() => ({
  values: [] as unknown[],
  next: 0,
  effects: [] as (() => unknown)[],
}));
vi.mock("react", async (importOriginal) => {
  const react = await importOriginal<typeof import("react")>();
  function useState(initial: unknown) {
    const index = hooks.next++;
    if (!(index in hooks.values)) hooks.values[index] = initial;
    return [
      hooks.values[index],
      (value: unknown) => {
        hooks.values[index] =
          typeof value === "function" ? value(hooks.values[index]) : value;
      },
    ];
  }
  return {
    ...react,
    useState,
    useRef: (current: unknown) => useState({ current })[0],
    useEffect: (effect: () => unknown) => {
      hooks.effects.push(effect);
    },
  };
});
vi.mock("./contract", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./contract")>()),
  streamCouncil: vi.fn(),
}));

type Props = {
  [key: string]: unknown;
  children?: ReactNode;
  ref?: { current: unknown };
  disabled?: boolean;
  onClick?: () => void;
  onDemo?: () => void;
  onCancel?: () => void;
  onSubmit?: (event: { preventDefault: () => void }) => void;
  onChange?: (event: { target: { value: string; files?: File[] } }) => void;
  onTranscript?: (text: string) => void;
  onBusyChange?: (busy: boolean) => void;
};
function find(node: ReactNode, key: string, value: unknown): Props | undefined {
  for (const child of Children.toArray(node)) {
    if (!isValidElement<Props>(child)) continue;
    if ((key === "type" ? child.type : child.props[key]) === value)
      return child.props;
    const nested = find(child.props.children, key, value);
    if (nested) return nested;
  }
}
function get(key: string, value: unknown): Props {
  hooks.next = 0;
  const props = find(App(), key, value);
  if (!props) throw new Error(`Missing ${key}=${value}`);
  return props;
}
function submitDetails(text: string) {
  (get("type", ProfileModal).onSubmit as unknown as (text: string) => void)(
    text,
  );
}
function submit(className: string) {
  get("className", className).onSubmit!({ preventDefault() {} });
}
async function idle() {
  await vi.waitFor(() =>
    expect(get("aria-label", "Send message")).toBeDefined(),
  );
}
const verdict: Verdict = {
  member: "buffett",
  signal: "HOLD",
  headline: "Returned portfolio answer. More context for details.",
  reasons: ["Returned reason"],
  sources: [],
  tickers: [],
  analysis: "",
  positions: [],
  advice: [],
};
async function replySession() {
  vi.mocked(streamCouncil).mockImplementationOnce(
    async (_, __, ___, receive) => {
      await receive({ event: "run.started", data: { run_id: "parent" } });
      await receive({ event: "member.verdict", data: verdict });
      await receive({ event: "run.done", data: { run_id: "parent" } });
    },
  );
  submit("chat-form");
  await vi.advanceTimersByTimeAsync(1200);
  get("className", "reply-button").onClick!();
  get("id", "message").onChange!({ target: { value: "Why hold?" } });
}

beforeEach(async () => {
  hooks.values = [];
  hooks.next = 0;
  hooks.effects = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (input === "/demo-portfolio.json")
      return Response.json(
        JSON.parse(
          readFileSync(
            new URL("../../data/portfolio.json", import.meta.url),
            "utf8",
          ),
        ),
      );
    if (input === "/demo-persona.md")
      return new Response(
        readFileSync(new URL("../../data/PERSONA.md", import.meta.url), "utf8"),
      );
    return Response.json({
      brief_id: "brief",
      summary: "Portfolio received",
      voice: true,
    });
  });
  vi.mocked(streamCouncil).mockReset();
  vi.mocked(streamCouncil).mockImplementation(async (_, __, ___, receive) => {
    await receive({ event: "run.started", data: { run_id: "parent" } });
    await receive({ event: "run.done", data: { run_id: "parent" } });
  });
  get("className", "chat-form");
  get("type", ProfileModal).onDemo!();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Jordan’s portfolio loaded",
    ),
  );
  get("id", "message").onChange!({ target: { value: "Should I hold?" } });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("auto-ingests the checked-in context and renders only chat with one composer", async () => {
  expect(fetch).toHaveBeenCalledWith(
    "/api/ingest",
    expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
  );
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  expect(html).toContain("Jordan’s portfolio loaded");
  expect(html).toContain("Jordan, 38 — context loaded");
  expect(html).toContain("$302,171 across 14 holdings");
  expect(html).toContain("Top positions: PLTR 18%, SPY 16%, NVDA 8%");
  expect(html).toContain("Cash: $18,431");
  expect(html).toContain("Goal: Multiply the money and invest it wisely.");
  expect(html).not.toContain("brief-form");
  expect(html).not.toContain("Upload portfolio");
  expect(html).not.toContain("Preview backend");
  expect(html.match(/<textarea/g)).toHaveLength(1);
  submit("chat-form");
  await idle();
  expect(streamCouncil).toHaveBeenCalledWith(
    "/api/council/run",
    expect.objectContaining({ brief_id: "brief", question: "Should I hold?" }),
    expect.any(AbortSignal),
    expect.any(Function),
  );
});

const SAM = "I'm Sam, 31. 40 shares of AAPL at $150, $8k in VOO, $12k cash.";
const samCard = {
  title: "Sam, 31 — context loaded",
  lines: [
    "2 holdings — total valuation unavailable",
    "Cash: $12,000",
    "Not given: goals",
  ],
};
function mockIngestText(response: Response, brief = "sam") {
  const demo = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, options) =>
    input === "/api/ingest/text"
      ? response.ok
        ? Response.json({ brief_id: brief, summary: "ok", card: samCard })
        : response
      : demo(input, options),
  );
}
async function openFresh() {
  hooks.values = [];
  hooks.next = 0;
  hooks.effects = [];
  vi.mocked(fetch).mockClear();
}

it("opens on the details box and loads nothing until a choice is made", async () => {
  await openFresh();
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  expect(html).toContain('aria-label="Your details"');
  expect(html).toContain("Waiting for your details");
  expect(fetch).not.toHaveBeenCalledWith("/api/ingest", expect.anything());
  expect(get("aria-label", "Send message").disabled).toBe(true);
  expect(get("type", ProfileModal).onCancel).toBeUndefined();
});

it("submits the user's own details and council runs on that brief", async () => {
  await openFresh();
  mockIngestText(Response.json({}));
  submitDetails(SAM);
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Your details loaded",
    ),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/ingest/text",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ text: SAM }),
    }),
  );
  expect(fetch).not.toHaveBeenCalledWith("/api/ingest", expect.anything());
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  expect(html).not.toContain('aria-label="Your details"'); // modal closed
  expect(html).toContain("Sam, 31 — context loaded");
  expect(html).toContain("Not given: goals");
  expect(html).toContain("Change my details");
  expect(html).not.toContain("Jordan");
  expect(html).not.toContain("Replace portfolio");
  get("id", "message").onChange!({ target: { value: "Should I sell AAPL?" } });
  submit("chat-form");
  await idle();
  expect(streamCouncil).toHaveBeenCalledWith(
    "/api/council/run",
    expect.objectContaining({ brief_id: "sam" }),
    expect.any(AbortSignal),
    expect.any(Function),
  );
});

it("keeps the box open with the server's message when the details are rejected", async () => {
  await openFresh();
  mockIngestText(
    Response.json(
      { detail: "The cash (50000) isn't in what you wrote." },
      { status: 422 },
    ),
  );
  submitDetails(SAM);
  await vi.waitFor(() =>
    expect(get("type", ProfileModal).error).toBe(
      "The cash (50000) isn't in what you wrote.",
    ),
  );
  expect(get("type", ProfileModal).busy).toBe(false);
  expect(get("className", "context-chip").children).toBe(
    "Waiting for your details",
  );
});

it("lets the user reopen the box, keeps their text, and switch back to the demo", async () => {
  await openFresh();
  mockIngestText(Response.json({}));
  submitDetails(SAM);
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Your details loaded",
    ),
  );
  get("className", "change-details").onClick!();
  expect(get("type", ProfileModal).initialText).toBe(SAM);
  expect(get("type", ProfileModal).onCancel).toBeDefined();
  get("type", ProfileModal).onDemo!();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Jordan’s portfolio loaded",
    ),
  );
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  expect(html).toContain("Jordan, 38 — context loaded");
  expect(html).toContain("Replace portfolio");
});

it.each(["details", "demo", "portfolio"])(
  "clears old suggestions when switching to %s and retains them on Cancel",
  async (destination) => {
    vi.useFakeTimers();
    const chip = "Should I reduce my old PLTR position?";
    vi.mocked(streamCouncil).mockImplementationOnce(
      async (_, __, ___, receive) => {
        await receive({ event: "run.started", data: { run_id: "parent" } });
        await receive({
          event: "chat.closed",
          data: { text: "", suggestions: [chip] },
        });
        await receive({ event: "run.done", data: { run_id: "parent" } });
      },
    );
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(1200);
    hooks.next = 0;
    expect(renderToStaticMarkup(App())).toContain(chip);
    get("className", "change-details").onClick!();
    get("type", ProfileModal).onCancel!();
    hooks.next = 0;
    expect(renderToStaticMarkup(App())).toContain(chip);
    if (destination === "portfolio") {
      get("aria-label", "Replace portfolio").onChange!({
        target: {
          value: "",
          files: [
            new File(["ticker,shares,cost_basis\nMSFT,7,200"], "new.csv"),
          ],
        },
      });
    } else {
      get("className", "change-details").onClick!();
      if (destination === "demo") get("type", ProfileModal).onDemo!();
      else {
        mockIngestText(Response.json({}));
        submitDetails(SAM);
      }
    }
    await vi.advanceTimersByTimeAsync(0);
    expect(get("className", "context-chip").children).toBe(
      destination === "details"
        ? "Your details loaded"
        : destination === "demo"
          ? "Jordan’s portfolio loaded"
          : "new.csv loaded",
    );
    expect(() => get("className", "chips")).toThrow("Missing");
    hooks.next = 0;
    expect(renderToStaticMarkup(App())).not.toContain(chip);
  },
);

it("re-ingests the user's text, not the demo, when the server forgets the brief", async () => {
  await openFresh();
  mockIngestText(Response.json({}));
  submitDetails(SAM);
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Your details loaded",
    ),
  );
  get("id", "message").onChange!({ target: { value: "Should I hold?" } });
  vi.mocked(streamCouncil)
    .mockRejectedValueOnce(new Error("unknown brief_id"))
    .mockImplementationOnce(async (_, body, __, receive) => {
      expect(body).toMatchObject({ brief_id: "sam-2" });
      await receive({ event: "run.started", data: { run_id: "r" } });
      await receive({ event: "run.done", data: { run_id: "r" } });
    });
  mockIngestText(Response.json({}), "sam-2");
  submit("chat-form");
  await idle();
  await vi.waitFor(() => expect(streamCouncil).toHaveBeenCalledTimes(2));
  expect(fetch).not.toHaveBeenCalledWith(
    "/demo-portfolio.json",
    expect.anything(),
  );
});

it("preserves typed text and blocks sending while a voice question is pending", async () => {
  get("type", VoiceInput).onBusyChange!(true);
  expect(get("aria-label", "Send message").disabled).toBe(true);
  submit("chat-form");
  expect(streamCouncil).not.toHaveBeenCalled();
  get("type", VoiceInput).onTranscript!("What changed?");
  get("type", VoiceInput).onBusyChange!(false);
  expect(get("id", "message").value).toBe("Should I hold? What changed?");
  submit("chat-form");
  await idle();
  expect(streamCouncil).toHaveBeenCalledWith(
    "/api/council/run",
    expect.objectContaining({ question: "Should I hold? What changed?" }),
    expect.any(AbortSignal),
    expect.any(Function),
  );
});

function keyOf(node: ReactNode, label: string): unknown {
  for (const child of Children.toArray(node)) {
    if (!isValidElement<Props>(child)) continue;
    if (child.props["aria-label"] === label) return child.key;
    const nested = keyOf(child.props.children, label);
    if (nested) return nested;
  }
}
it("keeps the send and cancel buttons as separate DOM nodes", async () => {
  vi.mocked(streamCouncil).mockImplementationOnce(
    (_, __, signal) =>
      new Promise<void>((_, reject) =>
        signal.addEventListener("abort", () => reject(signal.reason)),
      ),
  );
  hooks.next = 0;
  const idleKey = keyOf(App(), "Send message");
  submit("chat-form");
  await vi.waitFor(() => expect(streamCouncil).toHaveBeenCalledOnce());
  hooks.next = 0;
  const busyKey = keyOf(App(), "Cancel session");
  get("aria-label", "Cancel session").onClick!();
  await idle();
  expect(idleKey).toBeTruthy();
  expect(busyKey).toBeTruthy();
  expect(busyKey).not.toBe(idleKey);
});

it.each(["request failure", "cancellation", "stream error", "early end"])(
  "preserves the message and permits retry after %s",
  async (failure) => {
    if (failure === "cancellation") {
      vi.mocked(streamCouncil).mockImplementationOnce(
        (_, __, signal) =>
          new Promise<void>((_, reject) =>
            signal.addEventListener("abort", () => reject(signal.reason)),
          ),
      );
    } else if (failure === "stream error") {
      vi.mocked(streamCouncil).mockImplementationOnce(
        async (_, __, ___, receive) => {
          await receive({
            event: "run.error",
            data: { message: "Unavailable" },
          });
          throw new Error("Unavailable");
        },
      );
    } else vi.mocked(streamCouncil).mockRejectedValueOnce(new Error(failure));
    submit("chat-form");
    if (failure === "cancellation") {
      await vi.waitFor(() => expect(streamCouncil).toHaveBeenCalledOnce());
      get("aria-label", "Cancel session").onClick!();
    }
    await idle();
    expect(get("id", "message").value).toBe("Should I hold?");
    submit("chat-form");
    await idle();
    expect(streamCouncil).toHaveBeenCalledTimes(2);
    expect(get("id", "message").value).toBe("");
  },
);

it.each([
  ["unknown brief_id", false, "reload", false],
  ["unknown run_id", true, "replace", false],
  ["unknown brief_id", false, "replace", true],
  ["unknown run_id", true, "reload", true],
] as const)(
  "recovers from %s (follow-up: %s, recovery: %s, stream error: %s)",
  async (detail, follow, recovery, streamed) => {
    vi.useFakeTimers();
    if (follow) await replySession();
    const message = follow ? "Why hold?" : "Should I hold?";
    const fetchContext = vi.mocked(fetch).getMockImplementation()!;
    const { streamCouncil: requestCouncil } =
      await vi.importActual<typeof import("./contract")>("./contract");
    vi.mocked(streamCouncil).mockImplementationOnce(requestCouncil);
    // A lost brief is re-ingested and retried once, and a lost session reruns as a fresh one: the retry must fail too.
    vi.mocked(streamCouncil).mockImplementationOnce(requestCouncil);
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      if (input === "/api/council/run" || input === "/api/council/chat")
        return streamed
          ? new Response(
              `event: run.error\ndata: ${JSON.stringify({ message: detail })}\n\n`,
              { headers: { "Content-Type": "text/event-stream" } },
            )
          : Response.json({ detail }, { status: 404 });
      return fetchContext(input, options);
    });
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    expect(get("className", "context-chip").children).toBe(
      "Portfolio unavailable",
    );
    expect(get("id", "message").value).toBe(message);
    expect(get("aria-label", "Send message").disabled).toBe(true);
    expect(get("className", "error").children).toContain("context expired");
    expect(() => get("className", "reply-target")).toThrow("Missing");
    if (follow) expect(get("className", "reply-button").disabled).toBe(true);
    const calls = vi.mocked(streamCouncil).mock.calls.length;
    submit("chat-form");
    expect(streamCouncil).toHaveBeenCalledTimes(calls);

    vi.mocked(fetch).mockImplementation(async (input, options) =>
      input === "/api/ingest"
        ? Response.json({ brief_id: "fresh", summary: "Portfolio received" })
        : fetchContext(input, options),
    );
    if (recovery === "reload") {
      get("className", "context-retry").onClick!();
    } else {
      expect(get("aria-label", "Replace portfolio").disabled).toBe(false);
      get("aria-label", "Replace portfolio").onChange!({
        target: {
          value: "",
          files: [
            new File(
              ["ticker,shares,cost_basis\nAAPL,2,100"],
              "replacement.csv",
            ),
          ],
        },
      });
    }
    await vi.advanceTimersByTimeAsync(0);
    expect(get("className", "context-chip").children).toBe(
      recovery === "reload"
        ? "Jordan’s portfolio loaded"
        : "replacement.csv loaded",
    );
    expect(get("aria-label", "Send message").disabled).toBe(false);
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    expect(streamCouncil).toHaveBeenLastCalledWith(
      "/api/council/run",
      { brief_id: "fresh", question: message, roast: false },
      expect.any(AbortSignal),
      expect.any(Function),
    );
    expect(get("id", "message").value).toBe("");
    expect(vi.getTimerCount()).toBe(0);
  },
);

it("silently re-ingests a lost brief and retries the question once", async () => {
  vi.useFakeTimers();
  vi.mocked(streamCouncil)
    .mockRejectedValueOnce(new Error("unknown brief_id"))
    .mockImplementationOnce(async (_, __, ___, receive) => {
      await receive({ event: "run.started", data: { run_id: "again" } });
      await receive({ event: "run.done", data: { run_id: "again" } });
    });
  const fetchContext = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, options) =>
    input === "/api/ingest"
      ? Response.json({ brief_id: "fresh", summary: "Portfolio received" })
      : fetchContext(input, options),
  );
  submit("chat-form");
  await vi.advanceTimersByTimeAsync(0);
  expect(streamCouncil).toHaveBeenCalledTimes(2);
  expect(streamCouncil).toHaveBeenLastCalledWith(
    "/api/council/run",
    { brief_id: "fresh", question: "Should I hold?", roast: false },
    expect.any(AbortSignal),
    expect.any(Function),
  );
  expect(() => get("className", "error")).toThrow("Missing");
  expect(get("className", "context-chip").children).toBe(
    "Jordan’s portfolio loaded",
  );
});

it("shows real returned answers and ruling as avatar messages with full details", async () => {
  vi.useFakeTimers();
  vi.mocked(streamCouncil).mockImplementationOnce(
    async (_, __, ___, receive) => {
      await receive({ event: "member.verdict", data: verdict });
      await receive({
        event: "chair.summary",
        data: {
          overall_signal: "HOLD",
          summary: "Returned final ruling",
          consensus: "Returned consensus",
          dissent: ["Returned dissent"],
          actions: [],
          suggestions: [],
          positions: [],
        },
      });
      await receive({ event: "run.done", data: { run_id: "parent" } });
    },
  );
  submit("chat-form");
  await vi.advanceTimersByTimeAsync(1200);
  expect(get("active", "buffett").animation).toEqual({ buffett: "drumming" });
  await vi.advanceTimersByTimeAsync(1700);
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  for (const text of [
    "Should I hold?",
    verdict.headline,
    "Returned reason",
    "Returned final ruling",
    "Returned consensus",
    "Returned dissent",
    "chat-avatar",
  ])
    expect(html).toContain(text);
});

it("shows context failure, disables send, and retries the real loading path", async () => {
  const fetchContext = vi.mocked(fetch).getMockImplementation()!;
  hooks.values = [];
  hooks.next = 0;
  hooks.effects = [];
  vi.mocked(fetch).mockResolvedValue(
    new Response("Unavailable", { status: 503 }),
  );
  get("className", "chat-form");
  get("type", ProfileModal).onDemo!();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Portfolio unavailable",
    ),
  );
  expect(get("aria-label", "Send message").disabled).toBe(true);
  expect(get("className", "error").children).toContain("unavailable");
  vi.mocked(fetch).mockImplementation(fetchContext);
  get("className", "context-retry").onClick!();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Jordan’s portfolio loaded",
    ),
  );
});

it("clears old answers only after a replacement portfolio is accepted", async () => {
  vi.useFakeTimers();
  await replySession();
  vi.useRealTimers();
  const label = "Jordan’s portfolio loaded";
  vi.mocked(fetch).mockResolvedValueOnce(
    Response.json({ detail: "Invalid holdings" }, { status: 422 }),
  );
  const replace = () =>
    get("aria-label", "Replace portfolio").onChange!({
      target: {
        value: "",
        files: [
          new File(["ticker,shares,cost_basis\nAAPL,2,100"], "replacement.csv"),
        ],
      },
    });
  replace();
  await vi.waitFor(() =>
    expect(get("className", "error").children).toBe("Invalid holdings"),
  );
  expect(get("className", "context-chip").children).toBe(label);
  hooks.next = 0;
  expect(renderToStaticMarkup(App())).toContain(verdict.headline);
  replace();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "replacement.csv loaded",
    ),
  );
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  expect(html).not.toContain(verdict.headline);
  expect(html).not.toContain("reply-target");
  expect(html).not.toContain("chat-avatar");
});

it.each([
  [false, false],
  [false, true],
  [true, false],
  [true, true],
])(
  "retries the accepted upload after expiry (follow-up: %s, rejected replacement: %s)",
  async (follow, rejected) => {
    vi.useFakeTimers();
    const sentContext = async () => {
      const body = vi
        .mocked(fetch)
        .mock.calls.filter(([path]) => path === "/api/ingest")
        .at(-1)?.[1]?.body;
      if (!(body instanceof FormData)) throw new Error("Missing ingest form");
      return Object.fromEntries(
        await Promise.all(
          Array.from(body, async ([key, value]) => [
            key,
            typeof value === "string" ? value : await value.text(),
          ]),
        ),
      );
    };
    const initial = await sentContext();
    const csv = "ticker,shares,cost_basis\nMSFT,7,200";
    const holdings = JSON.stringify({
      holdings: [{ ticker: "MSFT", shares: 7, cost_basis: 200 }],
    });
    const uploaded = follow
      ? new File(
          [
            JSON.stringify({
              positions: [{ symbol: "MSFT", qty: 7, avg_entry_price: 200 }],
            }),
          ],
          "uploaded.json",
        )
      : new File([csv], "uploaded.csv");
    const replace = (file: File) =>
      get("aria-label", "Replace portfolio").onChange!({
        target: { value: "", files: [file] },
      });
    replace(uploaded);
    await vi.advanceTimersByTimeAsync(0);
    const accepted = await sentContext();
    expect(accepted).toEqual({
      portfolio: follow ? holdings : csv,
      persona: initial.persona,
      plaid: "false",
    });
    expect(get("className", "context-chip").children).toBe(
      `${uploaded.name} loaded`,
    );
    await replySession();
    if (!follow) get("className", "reply-target").onClick!();
    if (rejected) {
      vi.mocked(fetch).mockResolvedValueOnce(
        Response.json({ detail: "Invalid holdings" }, { status: 422 }),
      );
      replace(new File(["invalid"], "rejected.csv"));
      await vi.advanceTimersByTimeAsync(0);
      expect(get("className", "error").children).toBe("Invalid holdings");
      expect(get("className", "context-chip").children).toBe(
        `${uploaded.name} loaded`,
      );
    }
    const lost = new Error(follow ? "unknown run_id" : "unknown brief_id");
    vi.mocked(streamCouncil).mockRejectedValueOnce(lost);
    if (follow) vi.mocked(streamCouncil).mockRejectedValueOnce(lost);
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    expect(get("className", "context-chip").children).toBe(
      "Portfolio unavailable",
    );
    vi.mocked(fetch).mockClear();
    get("className", "context-retry").onClick!();
    await vi.advanceTimersByTimeAsync(0);
    expect(await sentContext()).toEqual(accepted);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(get("className", "context-chip").children).toBe(
      `${uploaded.name} loaded`,
    );
    expect(get("id", "message").value).toBe("Why hold?");
    expect(get("aria-label", "Send message").disabled).toBe(false);
    hooks.next = 0;
    expect(renderToStaticMarkup(App())).toContain(verdict.headline);
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    expect(streamCouncil).toHaveBeenLastCalledWith(
      "/api/council/run",
      { brief_id: "brief", question: "Why hold?", roast: false },
      expect.any(AbortSignal),
      expect.any(Function),
    );
    expect(vi.getTimerCount()).toBe(0);
  },
);

it("answers a follow-up as a fresh session when the server lost the run", async () => {
  vi.useFakeTimers();
  await replySession();
  vi.mocked(streamCouncil).mockRejectedValueOnce(new Error("unknown run_id"));
  submit("chat-form");
  await vi.advanceTimersByTimeAsync(0);
  expect(streamCouncil).toHaveBeenLastCalledWith(
    "/api/council/run",
    { brief_id: "brief", question: "Why hold?", roast: false },
    expect.any(AbortSignal),
    expect.any(Function),
  );
  expect(() => get("className", "error")).toThrow("Missing");
  expect(get("className", "context-chip").children).toBe(
    "Jordan’s portfolio loaded",
  );
});

describe("click-to-read answers", () => {
  it("never autoplays streamed audio and requests the selected member only on click", async () => {
    vi.useFakeTimers();
    const toggle = vi
      .spyOn(SpeechPlayback.prototype, "toggle")
      .mockResolvedValue();
    vi.mocked(streamCouncil).mockImplementationOnce(
      async (_, __, ___, receive) => {
        await receive({ event: "member.verdict", data: verdict });
        await receive({
          event: "member.audio",
          data: {
            member: "buffett",
            audio_url: "/api/voice/speak?text=ignored",
          },
        });
        await receive({
          event: "member.reply",
          data: { member: "chair", text: "Returned follow-up" },
        });
        await receive({ event: "run.done", data: { run_id: "parent" } });
      },
    );
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(1200);
    expect(toggle).not.toHaveBeenCalled();
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(([url]) => String(url).includes("/voice/")),
    ).toBe(false);
    hooks.next = 0;
    const html = renderToStaticMarkup(App());
    expect(html).not.toContain("<audio");
    expect(html).not.toContain("Sound on");
    get("type", ReadAloud).onClick!();
    expect(toggle).toHaveBeenCalledWith("chat-1", "buffett", verdict.headline);
  });
});
