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
        const scope = document.getElementById("scope-visual");
        const common = document.getElementById("scope-common");
        return {
          home: document.getElementById("home-type").textContent,
          privateText: document.getElementById("scope-private").textContent,
          boundaryText: document.getElementById("scene-boundary").textContent,
          householdText: document.getElementById("quick-household").textContent,
          wholeLabel: document.getElementById("whole-area-label").textContent,
          wholeArea: document.getElementById("whole-area").textContent,
          attributedArea: document.getElementById("attributed-area").textContent,
          attributedVisible: getComputedStyle(document.getElementById("attributed-area-box")).display !== "none",
          ownedArea: document.getElementById("owned-area").textContent,
          sharedAreaNoteVisible: getComputedStyle(document.getElementById("shared-area-note")).display !== "none",
          sharedAreaNote: document.getElementById("shared-area-note").textContent,
          scopeShared: scope.classList.contains("shared"),
          commonHidden: common.hasAttribute("hidden"),
          commonVisible: getComputedStyle(common).display !== "none",
          figureCount: document.querySelectorAll("#member-list .member-avatar svg").length,
          sceneVisible: getComputedStyle(document.querySelector(".house-scene")).display !== "none",
          overflow: document.documentElement.scrollWidth > innerWidth,
        };
      });
      assert.equal(state.scopeShared, shared);
      assert.equal(state.commonHidden, !shared);
      assert.equal(state.commonVisible, shared);
      assert.equal(state.privateText, shared ? "本户私有房间" : "本户独立居住范围");
      assert.match(state.boundaryText, shared ? /宽度不按面积比例；设备仅在本户控制范围内/ : /设备仅在约定控制范围内/);
      assert.equal(state.sceneVisible, true);
      assert.ok(state.figureCount > 0);
      assert.equal(state.overflow, false);
      assert.equal(state.home.includes("合住"), shared);
      assert.equal(state.attributedVisible, shared);
      assert.equal(state.sharedAreaNoteVisible, shared);
      assert.equal(state.wholeLabel, shared ? "整套模型设计建筑面积" : "整套设计建筑面积");
      if (shared) {
        assert.match(state.householdText, /^本户 \d+ 人/);
        assert.match(state.sharedAreaNote, /其他住户人数未设定/);
      }
      if (role === "cityrole-0020") {
        assert.equal(state.householdText.startsWith("本户 3 人"), true);
        assert.equal(state.attributedArea, "24.0 m²");
        assert.equal(state.wholeArea, "41.0 m²");
        assert.equal(state.ownedArea, "22.8 m²");
      }
    }
    await verify("cityrole-0001", false);
    await verify("cityrole-0004", true);
    await verify("cityrole-0020", true);
    await verify("cityrole-0001", false);
    await page.setViewportSize({ width: 490, height: 695 });
    await verify("cityrole-0020", true);
    await verify("cityrole-0004", true);
    await verify("cityrole-0001", false);
    console.log("Role SVG browser regression passed: ordinary/shared/ordinary and 490px viewport.");
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
