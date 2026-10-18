import { expect, test } from "@playwright/test";

for (const [width, height] of [
  [390, 844],
  [430, 932],
  [768, 1024],
  [1440, 900],
  [1600, 900],
]) {
  test(`fresh-user layout at ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await expect(page.locator(".council-seat")).toHaveCount(5);
    const bounds = await page.evaluate(() => {
      const rect = (selector: string) =>
        document.querySelector(selector)!.getBoundingClientRect().toJSON();
      const row = document.querySelector(".council-seats")!;
      return {
        pageWidth: document.documentElement.scrollWidth,
        scene: rect(".stage"),
        chat: rect(".chat-panel"),
        composer: rect(".chat-composer"),
        transcript: rect(".chat-messages"),
        rowScrolls: row.scrollWidth > row.clientWidth,
        targets: [
          ".send-message",
          ".attach-context",
          ".seat-label",
          ".toggle",
          ".brand",
        ].map(rect),
      };
    });
    expect(bounds.pageWidth).toBeLessThanOrEqual(width);
    expect(bounds.composer.bottom).toBeLessThanOrEqual(height + 1);
    expect(bounds.transcript.height).toBeGreaterThan(100);
    if (width <= 800) {
      expect(bounds.chat.top).toBeGreaterThanOrEqual(bounds.scene.bottom - 1);
      expect(bounds.rowScrolls).toBe(true);
      expect(bounds.composer.bottom).toBeGreaterThanOrEqual(height - 1);
      for (const target of bounds.targets) {
        expect(target.width).toBeGreaterThanOrEqual(44);
        expect(target.height).toBeGreaterThanOrEqual(44);
      }
    } else {
      expect(bounds.chat.left).toBeGreaterThanOrEqual(bounds.scene.right - 1);
      expect(bounds.chat.top).toBe(bounds.scene.top);
    }
    await expect(page.locator("audio")).toHaveCount(0);
  });
}

for (const [width, height] of [
  [390, 450],
  [430, 350],
  [768, 450],
  [1440, 900],
  [1600, 900],
]) {
  test(`composer remains reachable with suggestions and a recipient at ${width}x${height}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: Math.max(height, 844) });
    await page.route("**/api/ingest", (route) =>
      route.fulfill({
        json: { brief_id: "layout-brief", summary: "Accepted" },
      }),
    );
    const requests: unknown[] = [];
    await page.route("**/api/council/{run,chat}", async (route) => {
      requests.push(route.request().postDataJSON());
      const events = [
        ["run.started", { run_id: "layout-run" }],
        [
          "member.verdict",
          {
            member: "burry",
            headline: "Returned answer",
            analysis: "Returned analysis",
            positions: [],
            reasons: [],
            sources: [],
          },
        ],
        [
          "chat.closed",
          {
            text: "",
            suggestions: ["Explain the risks", "What should I consider next?"],
          },
        ],
        ["run.done", { run_id: "layout-run" }],
      ];
      await route.fulfill({
        contentType: "text/event-stream",
        body: events
          .map(
            ([event, data]) =>
              `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
          )
          .join(""),
      });
    });
    await page.goto("/");
    const input = page.getByRole("textbox", { name: "Message the council" });
    const send = page.getByRole("button", {
      name: "Send message",
      exact: true,
    });
    await input.fill("Review my portfolio");
    await expect(send).toBeEnabled();
    await send.click();
    await expect(page.locator(".chips button")).toHaveCount(2);
    await page.getByRole("button", { name: "Reply", exact: true }).click();
    await expect(page.locator(".reply-target")).toBeVisible();
    await input.fill("Why hold?");
    await input.focus();
    await page.setViewportSize({ width, height });
    if (width <= 800) {
      await page.mouse.move(width - 20, 100);
      await page.mouse.wheel(0, 1000);
      await page.mouse.move(width - 20, height - 20);
      await page.mouse.wheel(0, 1000);
      await expect(send).toBeInViewport({ ratio: 1 });
    }
    for (const control of [
      input,
      send,
      page.locator(".reply-target"),
      page.locator(".chips button").first(),
    ]) {
      await control.scrollIntoViewIfNeeded();
      await expect(control).toBeInViewport({ ratio: 1 });
    }
    await send.click();
    await expect.poll(() => requests.length).toBe(2);
    expect(requests[1]).toMatchObject({ text: "Why hold?", to: ["burry"] });
    const bounds = await page.evaluate(() => {
      const rect = (selector: string) =>
        document.querySelector(selector)!.getBoundingClientRect();
      return {
        pageWidth: document.documentElement.scrollWidth,
        pageHeight: document.documentElement.scrollHeight,
        scene: rect(".stage").toJSON(),
        chat: rect(".chat-panel").toJSON(),
      };
    });
    expect(bounds.pageWidth).toBeLessThanOrEqual(width);
    if (width <= 800) {
      expect(bounds.pageHeight).toBeLessThanOrEqual(height);
      expect(bounds.chat.top).toBeGreaterThanOrEqual(bounds.scene.bottom - 1);
    } else {
      expect(bounds.chat.left).toBeGreaterThanOrEqual(bounds.scene.right - 1);
      expect(bounds.chat.top).toBe(bounds.scene.top);
    }
  });
}
