export const members = {
  buffett: {
    name: "Warren Buffett",
    role: "The chair · fundamentals",
  },
  leopold: {
    name: "Leopold Aschenbrenner",
    role: "The AI optimist",
  },
  burry: { name: "Michael Burry", role: "The contrarian" },
  dalio: { name: "Ray Dalio", role: "Global macro" },
  cramer: { name: "Jim Cramer", role: "The momentum man" },
} as const;
export type Member = keyof typeof members;
export type Source = { title: string; url: string; quote?: string };
export type Verdict = {
  member: Member;
  signal: "BUY" | "HOLD" | "SELL";
  confidence: number;
  headline: string;
  reasons: string[];
  sources: Source[];
  tickers: string[];
};
export type Chair = {
  overall_signal: Verdict["signal"];
  consensus: string;
  dissent: string[];
  summary: string;
};
export type CouncilEvent =
  | { event: "run.started"; data: { run_id: string } }
  | { event: "member.status"; data: { member: Member; status: string } }
  | { event: "member.source"; data: Source & { member: Member } }
  | { event: "member.verdict"; data: Verdict }
  | { event: "chair.summary"; data: Chair }
  | { event: "member.audio"; data: { member: Member; audio_url: string } }
  | { event: "run.done"; data: { run_id: string } }
  | { event: "run.error"; data: { message: string } };

export function sourceUrl(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    if (
      !["https:", "http:"].includes(parsed.protocol) ||
      /(^|\.)example\.(com|org|net)$/.test(parsed.hostname)
    )
      return;
    return parsed.href;
  } catch {
    return;
  }
}

export function portfolioFile(value: unknown): File {
  if (typeof value !== "object" || value === null)
    throw new Error("The broker snapshot must be a JSON object.");
  const positions = (value as { positions?: unknown }).positions;
  if (!Array.isArray(positions) || !positions.length)
    throw new Error("The broker snapshot has no positions.");
  const holdings = positions.map((value: unknown) => {
    if (typeof value !== "object" || value === null)
      throw new Error("Each broker position must be an object.");
    const position = value as {
      symbol?: unknown;
      qty?: unknown;
      avg_entry_price?: unknown;
    };
    if (
      typeof position.symbol !== "string" ||
      !position.symbol.trim() ||
      typeof position.qty !== "number" ||
      !Number.isFinite(position.qty) ||
      position.qty <= 0 ||
      typeof position.avg_entry_price !== "number" ||
      !Number.isFinite(position.avg_entry_price) ||
      position.avg_entry_price < 0
    )
      throw new Error(
        "Each broker position needs a symbol, positive quantity and entry price.",
      );
    return {
      ticker: position.symbol,
      shares: position.qty,
      cost_basis: position.avg_entry_price,
    };
  });
  return new File([JSON.stringify({ holdings })], "portfolio.json", {
    type: "application/json",
  });
}

export async function ingestPortfolio(file: File): Promise<File> {
  if (file.name.toLowerCase().endsWith(".json")) {
    const value: unknown = JSON.parse(await file.text());
    if (typeof value === "object" && value !== null && "positions" in value)
      return portfolioFile(value);
  }
  return file;
}

export async function apiError(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null);
  return new Error(
    typeof body?.detail === "string"
      ? body.detail
      : `Server request failed (${response.status}). Please try again.`,
  );
}

// POST streaming needs fetch: EventSource cannot send the request body.
export async function streamCouncil(
  path: string,
  body: object,
  signal: AbortSignal,
  receive: (event: CouncilEvent) => Promise<void>,
) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw await apiError(response);
  if (!response.body)
    throw new Error("The server did not return a council stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      if (buffer.length > 1_000_000)
        throw new Error("The council returned an oversized event.");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const event = frame
          .split("\n")
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!event || !data) continue;
        if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
        const parsed = JSON.parse(data);
        if (
          event.startsWith("member.") &&
          !Object.hasOwn(members, parsed.member)
        )
          throw new Error("The server returned an unknown council member.");
        await receive({ event, data: parsed } as CouncilEvent);
        if (event === "run.error")
          throw new Error(parsed.message || "The council could not finish.");
        if (event === "run.done") completed = true;
      }
      if (done) break;
    }
    if (!completed)
      throw new Error("The council connection ended early. Please retry.");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
