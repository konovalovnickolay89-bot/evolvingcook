#!/usr/bin/env node
/**
 * UX evaluation measurements — how far down the page the first dish row sits,
 * and how tall the pre-board furniture is, on a phone viewport. Uses the same
 * stubbed contract fixtures as ux-eval-capture.mjs.
 */
import { chromium } from "playwright";

const BASE = process.argv[2] || "http://127.0.0.1:8080";
const API = "https://api.apidiscoverysolution.uk/api/v1";
const TODAY = new Date().toISOString().slice(0, 10);

const MODE = process.argv[3] === "counts" ? "counts" : "ordering";

const browser = await chromium.launch({ args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const ctx = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
});
const page = await ctx.newPage();

// Minimal stub: enough to render a skybar board with 9 dishes, one of them 86.
await page.route(`${API}/**`, async (route) => {
  const p = new URL(route.request().url()).pathname.replace("/api/v1", "");
  const body = (v) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(v) });
  if (p === "/version") return body({ contract_version: "0.1.18" });
  if (p === "/boards/storage-areas") return body([]);
  if (p.endsWith("/log")) return body({ service_date: TODAY, section: "skybar", open_count: 3, lines: [], by_kind: {} });
  if (p.includes("/sections/")) {
    return body({
      service_date: TODAY,
      day_status: "open",
      section: "skybar",
      section_id: 1,
      active: true,
      covers: null,
      covers_source: "none",
      notes: "",
      beo_events: [],
      outturn: {},
      waves: [],
      outlets: [],
      line_count: 9,
      ticked_count: 0,
      section_mode: MODE,
      mode_prompt_needed: false,
      guided: false,
      mode_recommendation: "ordering",
      prep_plan: null,
      qty_draft: null,
      order_assist: null,
      lines: Array.from({ length: 9 }, (_, i) => ({
        id: i + 1,
        name: `Dish ${i + 1}`,
        mode: "check",
        kind: "dish",
        category: "cocktails",
        unit: "ea",
        status: i === 2 ? "eighty_six" : "planned",
        ticked: false,
        supports_lounge: false,
        source: "template",
        notes: "",
        template_notes: "",
        sort_order: i,
        components: [],
        events: [],
        wave_allocations: [],
        ingredient_count: 4,
        to_order_count: 1,
        order_summary_label: "4 items · 1 to order",
      })),
    });
  }
  return body({});
});

await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
await page.evaluate(() => {
  localStorage.setItem("ec.access_token", "stub");
  localStorage.setItem("ec.token_expires_at", String(Date.now() + 86400000));
});
await page.goto(`${BASE}/#/board/${TODAY}/skybar`, { waitUntil: "networkidle" });
await page.waitForTimeout(800);

const m = await page.evaluate(() => {
  const y = (sel) => {
    const el = document.querySelector(sel);
    return el ? Math.round(el.getBoundingClientRect().top + window.scrollY) : null;
  };
  const h = (sel) => {
    const el = document.querySelector(sel);
    return el ? Math.round(el.getBoundingClientRect().height) : null;
  };
  return {
    viewportHeight: window.innerHeight,
    documentHeight: document.documentElement.scrollHeight,
    faceToggleTop: y(".face-toggle"),
    progressStripTop: y(".progress-strip"),
    stationLogTop: y(".station-log"),
    stationLogHeight: h(".station-log"),
    boardTop: y(".board"),
    firstDishRowTop: y(".board .board-row"),
    dishRows: document.querySelectorAll(".board .board-row").length,
    rowsFlaggedEightySix: document.querySelectorAll(".board .board-row--86").length,
    checkStateBadges: document.querySelectorAll(".board .board-row__check-state").length,
  };
});

console.log(JSON.stringify({ sectionMode: MODE, ...m }, null, 2));
await browser.close();
