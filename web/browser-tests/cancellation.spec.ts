import { once } from "node:events";
import { createServer } from "node:http";
import { expect, test } from "@playwright/test";

for (const followUp of [false, true]) {
  test(`cancelling an ${followUp ? "in-progress follow-up" : "initial question"} preserves the question without resending`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const requests: string[] = [];
    const server = createServer((request, response) => {
      response.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Access-Control-Allow-Origin": "*",
      });
      response.write('event: run.started\ndata: {"run_id":"cancel-run"}\n\n');
      if (followUp && request.url === "/api/council/run") {
        response.end(
          'event: member.reply\ndata: {"member":"chair","text":"Returned answer"}\n\nevent: run.done\ndata: {"run_id":"cancel-run"}\n\n',
        );
      }
    });
    try {
      server.listen(0, "127.0.0.1");
      await once(server, "listening");
      const address = server.address();
      if (!address || typeof address === "string")
        throw new Error("Council stream server did not start");
      await page.route("**/api/ingest", (route) =>
        route.fulfill({
          json: { brief_id: "cancel-brief", summary: "Accepted" },
        }),
      );
      await page.route("**/api/council/{run,chat}", async (route) => {
        const path = new URL(route.request().url()).pathname;
        requests.push(path);
        await route.continue({
          url: `http://127.0.0.1:${address.port}${path}`,
        });
      });
      await page.goto("/");
      await page
        .getByRole("button", { name: "Use the demo", exact: true })
        .click();
      const input = page.getByRole("textbox", { name: "Message the council" });
      const send = page.getByRole("button", {
        name: "Send message",
        exact: true,
      });
      if (followUp) {
        await input.fill("Review my portfolio");
        await send.click();
        await expect(
          page.getByText("Returned answer", { exact: true }),
        ).toBeVisible();
        await expect(input).toBeEnabled();
      }
      const question = followUp ? "What are the risks?" : "Should I hold?";
      await input.fill(question);
      const stream = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname ===
          `/api/council/${followUp ? "chat" : "run"}`,
      );
      await send.click();
      await stream;
      await expect(input).toBeDisabled();
      await page
        .getByRole("button", { name: "Cancel session", exact: true })
        .click();
      await expect(page.getByRole("alert")).toHaveText(
        "Council cancelled. Your message is preserved.",
      );
      await expect(input).toHaveValue(question);
      await expect(send).toBeEnabled();
      expect(requests).toEqual(
        followUp
          ? ["/api/council/run", "/api/council/chat"]
          : ["/api/council/run"],
      );
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
}
