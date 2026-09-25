"use strict";
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

async function main() {
  const origin = process.env.EB_BROWSER_ORIGIN;
  if (!origin) throw new Error("EB_BROWSER_ORIGIN is required");
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
  try {
    const page = await browser.newPage();
    await page.goto(`${origin}/roles`);
    await page.locator("#role-choice").waitFor({ state: "visible" });
    async function verify(role, shared) {
      await page.locator("#role-choice").selectOption(role);
      await page.waitForFunction(id => document.getElementById("role-code").textContent === id, role);
      const state = await page.evaluate(() => {
        const unit = document.getElementById("unit-diagram");
        const sharedDiagram = document.getElementById("shared-diagram");
        return {
          home: document.getElementById("home-type").textContent,
          unitHidden: unit.hasAttribute("hidden"),
          sharedHidden: sharedDiagram.hasAttribute("hidden"),
          unitVisible: getComputedStyle(unit).display !== "none",
          sharedVisible: getComputedStyle(sharedDiagram).display !== "none",
          overflow: document.documentElement.scrollWidth > innerWidth,
        };
      });
      assert.equal(state.unitHidden, shared);
      assert.equal(state.sharedHidden, !shared);
      assert.equal(state.unitVisible, !shared);
      assert.equal(state.sharedVisible, shared);
      assert.equal(state.overflow, false);
      assert.equal(state.home.includes("合住"), shared);
    }
    await verify("cityrole-0001", false);
    await verify("cityrole-0004", true);
    await verify("cityrole-0001", false);
    await page.setViewportSize({ width: 490, height: 695 });
    await verify("cityrole-0004", true);
    await verify("cityrole-0001", false);
    console.log("Role SVG browser regression passed: ordinary/shared/ordinary and 490px viewport.");
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
