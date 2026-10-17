import { Children, isValidElement } from "react";
import type { ReactNode } from "react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { streamCouncil } from "./contract";

const hooks = vi.hoisted(() => ({ values: [] as unknown[], next: 0 }));
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
    useEffect: () => {},
  };
});
vi.mock("./contract", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./contract")>()),
  streamCouncil: vi.fn(),
}));

type Props = {
  [key: string]: unknown;
  children?: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  onSubmit?: (event: { preventDefault: () => void }) => void;
  onChange?: (event: { target: { value: string; files?: File[] } }) => void;
};
function find(node: ReactNode, key: string, value: string): Props | undefined {
  for (const child of Children.toArray(node)) {
    if (!isValidElement<Props>(child)) continue;
    if (child.props[key] === value) return child.props;
    const nested = find(child.props.children, key, value);
    if (nested) return nested;
  }
}
function get(key: string, value: string): Props {
  hooks.next = 0;
  const props = find(App(), key, value);
  if (!props) throw new Error(`Missing ${key}=${value}`);
  return props;
}
function submit(className: string) {
  get("className", className).onSubmit!({ preventDefault() {} });
}
async function idle() {
  await vi.waitFor(() => {
    expect(get("className", "follow-form")).toBeDefined();
  });
}

beforeEach(() => {
  hooks.values = [];
  hooks.next = 0;
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    Response.json({ brief_id: "brief", summary: "Portfolio received" }),
  );
  vi.mocked(streamCouncil).mockReset();
  vi.mocked(streamCouncil).mockImplementation(async (_, __, ___, receive) => {
    await receive({ event: "run.started", data: { run_id: "parent" } });
    await receive({ event: "run.done", data: { run_id: "parent" } });
  });
  get("aria-label", "Upload portfolio").onChange!({
    target: {
      value: "",
      files: [new File(["ticker,shares,cost_basis\nAAPL,2,100"], "holdings.csv")],
    },
  });
  get("id", "persona").onChange!({ target: { value: "Long-term investor" } });
  get("id", "question").onChange!({ target: { value: "Should I hold?" } });
});
afterEach(() => vi.restoreAllMocks());

it.each(["request failure", "cancellation", "stream error", "early end"])(
  "allows another follow-up after %s without a new parent session",
  async (failure) => {
    submit("brief-form");
    await idle();
    get("id", "follow-question").onChange!({ target: { value: "Why hold?" } });
    if (failure === "cancellation") {
      vi.mocked(streamCouncil).mockImplementationOnce(
        (_, __, signal) =>
          new Promise<void>((_, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason));
          }),
      );
    } else if (failure === "stream error") {
      vi.mocked(streamCouncil).mockImplementationOnce(
        async (_, __, ___, receive) => {
          await receive({ event: "run.error", data: { message: "Unavailable" } });
          throw new Error("Unavailable");
        },
      );
    } else {
      vi.mocked(streamCouncil).mockRejectedValueOnce(
        new Error(
          failure === "early end" ? "Connection ended early" : "HTTP 503",
        ),
      );
    }
    submit("follow-form");
    if (failure === "cancellation")
      get("className", "text-button cancel").onClick!();
    await idle();
    expect(get("className", "primary").disabled).toBe(false);
    expect(get("id", "follow-question").value).toBe("Why hold?");
    submit("follow-form");
    await idle();
    expect(streamCouncil).toHaveBeenLastCalledWith(
      "/api/council/ask",
      expect.objectContaining({ run_id: "parent", question: "Why hold?" }),
      expect.any(AbortSignal),
      expect.any(Function),
    );
    expect(get("id", "follow-question").value).toBe("");
  },
);

it("requires completion again when a new parent session fails", async () => {
  submit("brief-form");
  await idle();
  get("className", "text-button start-over").onClick!();
  vi.mocked(streamCouncil).mockImplementationOnce(async (_, __, ___, receive) => {
    await receive({ event: "run.started", data: { run_id: "new-parent" } });
    throw new Error("HTTP 503");
  });
  submit("brief-form");
  await idle();
  get("id", "follow-question").onChange!({ target: { value: "Why hold?" } });
  expect(get("className", "primary").disabled).toBe(true);
});
