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
