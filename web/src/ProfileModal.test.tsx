import { beforeEach, expect, it, vi } from "vitest";
import type { ReactElement, ReactNode } from "react";
import ProfileModal, { PROFILE_PLACEHOLDER } from "./ProfileModal";

const hooks = vi.hoisted(() => ({ values: [] as unknown[], next: 0 }));
vi.mock("react", () => {
  function useState(initial: unknown) {
    const index = hooks.next++;
    if (!(index in hooks.values)) hooks.values[index] = initial;
    return [
      hooks.values[index],
      (value: unknown) => {
        hooks.values[index] = value;
      },
    ];
  }
  return {
    useState,
    useRef: (current: unknown) => useState({ current })[0],
    useEffect: () => {},
  };
});

type El = ReactElement<{
  [key: string]: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  children?: ReactNode;
}>;
function all(node: ReactNode, out: El[] = []): El[] {
  if (Array.isArray(node)) node.forEach((child) => all(child, out));
  else if (node && typeof node === "object") {
    out.push(node as El);
    all((node as El).props.children, out);
  }
  return out;
}
const onSubmit = vi.fn();
const onDemo = vi.fn();
const onCancel = vi.fn();
function view(props: Partial<Parameters<typeof ProfileModal>[0]> = {}) {
  hooks.next = 0;
  const tree = ProfileModal({
    initialText: "",
    busy: false,
    error: "",
    onSubmit,
    onDemo,
    ...props,
  });
  const els = all(tree);
  const find = (type: string, key: string, value: unknown) =>
    els.find((e) => e.type === type && e.props[key] === value)!;
  return {
    form: els.find((e) => e.type === "form")!,
    box: find("textarea", "id", "profile-details"),
    submit: find("button", "className", "profile-submit"),
    demo: find("button", "className", "profile-demo"),
    cancel: els.find((e) => e.props.className === "profile-cancel"),
    error: els.find((e) => e.props.role === "alert"),
  };
}
beforeEach(() => {
  hooks.values = [];
  vi.clearAllMocks();
});

it("shows one box with the example placeholder, Submit and Use the demo", () => {
  const v = view();
  expect(v.box.props.placeholder).toBe(PROFILE_PLACEHOLDER);
  expect(v.submit.props.children).toBe("Submit");
  expect(v.demo.props.children).toBe("Use the demo");
  expect(v.cancel).toBeUndefined();
  expect(v.submit.props.disabled).toBe(true); // nothing typed yet
});

it("submits the trimmed text and never submits an empty box", () => {
  const event = { preventDefault: vi.fn() };
  view().form.props.onSubmit(event);
  expect(onSubmit).not.toHaveBeenCalled();
  view().box.props.onChange({
    target: { value: "  I'm Sam, 40 shares of AAPL at $150  " },
  });
  const v = view();
  expect(v.submit.props.disabled).toBe(false);
  v.form.props.onSubmit(event);
  expect(onSubmit).toHaveBeenCalledWith("I'm Sam, 40 shares of AAPL at $150");
  expect(event.preventDefault).toHaveBeenCalled();
});

it("submits free-form holdings as typed: indexes, gold, crypto, accounts and misspellings", () => {
  const entry =
    "I'm Tom. 50k in ISA/stocks. Mostly AI. / I have some palanatir 1000 / Meta 2000 / Sp500 10000 / Gold 5000 / BTC 6000";
  view().box.props.onChange({ target: { value: entry } });
  const v = view();
  expect(v.submit.props.disabled).toBe(false);
  v.form.props.onSubmit({ preventDefault: vi.fn() });
  expect(onSubmit).toHaveBeenCalledWith(entry);
});

it("the demo button runs the demo", () => {
  view().demo.props.onClick();
  expect(onDemo).toHaveBeenCalledOnce();
  expect(onSubmit).not.toHaveBeenCalled();
});

it("shows errors, locks the box while busy, and offers Cancel only when there is a context to return to", () => {
  const v = view({
    error: "No holdings found",
    busy: true,
    initialText: "x",
    onCancel,
  });
  expect(v.error?.props.children).toBe("No holdings found");
  expect(v.submit.props.disabled).toBe(true);
  expect(v.submit.props.children).toBe("Reading your details…");
  expect(v.demo.props.disabled).toBe(true);
  expect(v.box.props.disabled).toBe(true);
  expect(v.cancel?.props.disabled).toBe(true);
  view({ onCancel }).cancel!.props.onClick();
  expect(onCancel).toHaveBeenCalledOnce();
});
