#!/usr/bin/env node
/**
 * UX evaluation capture — screenshots of the CURRENT build with the live API
 * stubbed, so the shots show real component code (not a mock of the UI) without
 * needing kitchen credentials.
 *
 * Fixtures mirror contract 0.1.18 shapes (BoardOut / ProductionLineOut /
 * StationLogOut / ServiceDayOut / ProposalOut).
 *
 *   node scripts/ux-eval-capture.mjs [baseUrl] [outDir]
 */
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.argv[2] || "http://127.0.0.1:8080";
const OUT = process.argv[3] || "/workspace/screenshots/ux-eval-2026-08";
const API = "https://api.apidiscoverysolution.uk/api/v1";

mkdirSync(OUT, { recursive: true });

const TODAY = new Date().toISOString().slice(0, 10);

const SECTIONS = [
  "skybar",
  "breakfast_buffet",
  "a_la_carte",
  "banquet_buffet",
  "banqueting",
  "canteen",
];

const day = {
  id: 1,
  service_date: TODAY,
  status: "open",
  occupancy_rooms: 214,
  occupancy_guests: 361,
  notes: "",
  opened_at: `${TODAY}T05:12:00Z`,
  closed_at: null,
  outturn: {},
  sections: SECTIONS.map((section, i) => ({
    id: i + 1,
    section,
    active: true,
    covers: section.startsWith("banquet") ? 180 : null,
    covers_source: "manual",
    notes: "",
    line_count: section === "skybar" ? 9 : 12,
    beo_events: [],
    outturn: {},
  })),
};

function comp(id, name, over = {}) {
  return {
    id,
    item_id: 400 + id,
    item_name: name,
    item_house_made: false,
    item_notes: null,
    supplier_item_id: 900 + id,
    name,
    planned_qty: 2,
    unit: "ea",
    done: false,
    sort_order: id,
    stock_status: "in_stock",
    stock_status_text: "in stock",
    stock_qty: 6,
    on_order_qty: 0,
    supplier_code: `SC-${1000 + id}`,
    par_qty: 4,
    stock_primary_qty: 3,
    primary_area_id: 7,
    primary_area_name: "Skybar cellar",
    stock_by_area: [
      { area_id: 7, area_name: "Skybar cellar", qty: 3 },
      { area_id: 1, area_name: "Walk-in fridge", qty: 3 },
    ],
    ...over,
  };
}

function line(id, name, over = {}) {
  return {
    id,
    name,
    mode: "check",
    kind: "dish",
    category: "cocktails",
    unit: "ea",
    item_id: 100 + id,
    item_name: name,
    item_notes: null,
    item_house_made: false,
    proposed_qty: null,
    planned_qty: null,
    actual_qty: null,
    par_level: null,
    status: "planned",
    ticked: false,
    supports_lounge: false,
    source: "template",
    notes: "",
    template_notes: "",
    sort_order: id,
    template_id: 10 + id,
    yield_per_cover: null,
    pending_proposal: null,
    components: [],
    events: [],
    wave_allocations: [],
    ingredient_count: 0,
    to_order_count: 0,
    order_summary_label: null,
    ...over,
  };
}

const skybarLines = [
  line(1, "Wembley Spritz", {
    order_summary_label: "6 items · 2 to order",
    ingredient_count: 6,
    to_order_count: 2,
    components: [
      comp(1, "Aperol 70cl", { stock_status: "running_low", stock_status_text: "running low" }),
      comp(2, "Prosecco Extra Dry", { stock_status: "on_order", stock_status_text: "on order" }),
      comp(3, "Orange (case)", { stock_status: "in_stock", stock_status_text: "in stock" }),
      comp(4, "Soda 200ml", { stock_status: "unknown", stock_status_text: "not counted" }),
    ],
  }),
  line(2, "Negroni", {
    order_summary_label: "4 items · 1 to order",
    ingredient_count: 4,
    to_order_count: 1,
    notes: "gin swap while Beefeater is out",
    components: [comp(5, "Campari 70cl"), comp(6, "Sweet vermouth")],
  }),
  line(3, "Truffle arancini (6)", {
    status: "eighty_six",
    order_summary_label: "5 items · 0 to order",
    ingredient_count: 5,
    template_notes: "fry to order, 3 min",
    components: [comp(7, "Arancini frozen 60g")],
  }),
  line(4, "Skybar sliders", {
    order_summary_label: "7 items · 3 to order",
    ingredient_count: 7,
    to_order_count: 3,
    components: [comp(8, "Brioche slider bun", { stock_status: "running_low", stock_status_text: "running low" })],
  }),
  line(5, "Padrón peppers", { order_summary_label: "3 items", ingredient_count: 3, components: [comp(9, "Padrón peppers 1kg")] }),
  line(6, "Olives & almonds", { order_summary_label: "2 items", ingredient_count: 2, components: [] }),
  line(7, "Espresso martini", { order_summary_label: "4 items · 1 to order", ingredient_count: 4, to_order_count: 1, components: [] }),
  line(8, "Charcuterie board", { order_summary_label: "8 items", ingredient_count: 8, components: [] }),
  line(9, "Loaded fries", { order_summary_label: "5 items", ingredient_count: 5, components: [] }),
];

const canteenLines = [
  line(21, "Staff stew", {
    mode: "produce",
    category: "hot",
    proposed_qty: 25,
    planned_qty: 25,
    actual_qty: 12,
    unit: "portion",
    components: [
      comp(21, "Diced beef 5kg", { done: true }),
      comp(22, "Onions 10kg"),
      comp(23, "Beef stock 5L"),
    ],
  }),
  line(22, "Rice pilaf", {
    mode: "produce",
    proposed_qty: 30,
    planned_qty: 24,
    actual_qty: 24,
    unit: "portion",
    ticked: true,
    components: [comp(24, "Basmati 5kg", { done: true })],
  }),
  line(23, "Seasonal veg", {
    mode: "produce",
    proposed_qty: 20,
    planned_qty: 20,
    actual_qty: null,
    unit: "portion",
    notes: "no broccoli — swapped to green beans",
    components: [],
  }),
  line(24, "Soup of the day", { mode: "produce", proposed_qty: 18, planned_qty: 18, actual_qty: 0, unit: "L", components: [] }),
  line(25, "Salad bar top-up", { mode: "replenish", par_level: 6, actual_qty: 2, planned_qty: 4, unit: "tray", components: [] }),
];

function board(section, over = {}) {
  return {
    service_date: TODAY,
    day_status: "open",
    occupancy_rooms: 214,
    occupancy_guests: 361,
    section,
    section_id: SECTIONS.indexOf(section) + 1,
    active: true,
    covers: null,
    covers_source: "none",
    notes: "",
    beo_events: [],
    outturn: {},
    waves: [],
    outlets: [],
    lines: [],
    line_count: 0,
    ticked_count: 0,
    section_mode: null,
    mode_prompt_needed: false,
    guided: false,
    mode_recommendation: null,
    prep_plan: null,
    qty_draft: null,
    order_assist: null,
    ...over,
  };
}

const boards = {
  skybar: board("skybar", {
    lines: skybarLines,
    line_count: skybarLines.length,
    section_mode: "ordering",
    mode_prompt_needed: false,
    mode_recommendation: "ordering",
    order_assist: {
      proposal_id: 12,
      kind: "order_suggest",
      target: "order_packs",
      rationale: "Aperol and slider buns below par for tonight's Skybar covers.",
      lines: [
        { item_id: 401, name: "Aperol 70cl", packs: 2, why: "par 4 · 1 in cellar" },
        { item_id: 408, name: "Brioche slider bun", packs: 3, why: "par 6 · 2 left" },
      ],
      accept_able: true,
    },
  }),
  canteen: board("canteen", {
    lines: canteenLines,
    line_count: canteenLines.length,
    ticked_count: 1,
    section_mode: "counts",
    mode_prompt_needed: false,
    mode_recommendation: "counts",
    qty_draft: {
      section: "canteen",
      service_date: TODAY,
      items: [
        {
          proposal_id: 31,
          kind: "morning_qty",
          status: "pending",
          accept_able: true,
          line_id: 21,
          line_name: "Staff stew",
          planned_qty: 25,
          unit: "portion",
          working: "board proposed/planned = 25",
          phase: "mep",
          order_index: 0,
          clock_time: null,
          target: "planned_qty",
        },
      ],
    },
  }),
  a_la_carte: board("a_la_carte", {
    lines: skybarLines.slice(0, 4).map((l) => ({ ...l, id: l.id + 50 })),
    line_count: 4,
    section_mode: null,
    mode_prompt_needed: true,
    mode_recommendation: "ordering",
  }),
};

const stationLog = (section) => {
  const rows = [
    {
      id: 1,
      kind: "leftover",
      text: "Pork belly tray from yesterday",
      action: "check",
      qty: 4,
      unit: "portion",
      area_id: 1,
      area_name: "Walk-in fridge",
      item_id: null,
      item_name: "",
      default_area: null,
      line_id: null,
      use_by: null,
      status: "open",
      source: "carry",
      carried_from_id: 44,
      from_yesterday: true,
      walk_count: null,
      created_at: `${TODAY}T05:30:00Z`,
      done_at: null,
    },
    {
      id: 2,
      kind: "mep",
      text: "Cut garnish for spritz service",
      action: "prep",
      qty: null,
      unit: "",
      area_id: null,
      area_name: "",
      item_id: null,
      item_name: "",
      default_area: null,
      line_id: null,
      use_by: null,
      status: "open",
      source: "suggest",
      carried_from_id: null,
      from_yesterday: false,
      walk_count: null,
      created_at: `${TODAY}T06:10:00Z`,
      done_at: null,
    },
    {
      id: 3,
      kind: "expire_soon",
      text: "Cream 2L use by tonight",
      action: "check",
      qty: 2,
      unit: "L",
      area_id: 7,
      area_name: "Skybar cellar",
      item_id: null,
      item_name: "",
      default_area: null,
      line_id: null,
      use_by: TODAY,
      status: "open",
      source: "suggest",
      carried_from_id: null,
      from_yesterday: false,
      walk_count: null,
      created_at: `${TODAY}T06:12:00Z`,
      done_at: null,
    },
    {
      id: 4,
      kind: "holding",
      text: "Slider patties portioned, hot hold",
      action: "hold",
      qty: 30,
      unit: "ea",
      area_id: 1,
      area_name: "Walk-in fridge",
      item_id: null,
      item_name: "",
      default_area: null,
      line_id: null,
      use_by: null,
      status: "done",
      source: "chef",
      carried_from_id: null,
      from_yesterday: false,
      walk_count: null,
      created_at: `${TODAY}T06:40:00Z`,
      done_at: `${TODAY}T07:02:00Z`,
    },
  ];
  const by_kind = {};
  for (const r of rows) (by_kind[r.kind] ??= []).push(r);
  return {
    service_date: TODAY,
    section,
    open_count: rows.filter((r) => r.status === "open").length,
    lines: rows,
    by_kind,
  };
};

const proposals = [
  {
    id: 51,
    kind: "parse_note",
    context: { section: "skybar", line_id: 2, line_name: "Negroni" },
    proposal: { note: "Swap Beefeater for Tanqueray until Thursday delivery" },
    target: "template",
    target_confidence: "high",
    rationale: "Note reads as a standing swap for this dish. | audit: note_parser v3",
    model: "hermes",
    status: "pending",
    decided_at: null,
    reject_reason: "",
    task_id: null,
    job_id: 9,
    parse_error: "",
    accept_able: true,
    created_at: new Date(Date.now() - 26 * 60000).toISOString(),
    updated_at: new Date(Date.now() - 26 * 60000).toISOString(),
  },
  {
    id: 52,
    kind: "parse_note",
    context: { section: "skybar", text: "2 crt oat + chk cellar b4 6" },
    proposal: {},
    target: null,
    target_confidence: "low",
    rationale: "",
    model: "hermes",
    status: "pending",
    decided_at: null,
    reject_reason: "",
    task_id: null,
    job_id: 10,
    parse_error: "Could not resolve item from abbreviation",
    accept_able: false,
    created_at: new Date(Date.now() - 8 * 60000).toISOString(),
    updated_at: new Date(Date.now() - 8 * 60000).toISOString(),
  },
  {
    id: 53,
    kind: "component_fill",
    context: { section: "skybar", line_id: 4, line_name: "Skybar sliders" },
    proposal: {
      note: "Add brioche bun, patty, burger cheese to Skybar sliders",
      components: [
        { name: "Brioche slider bun", qty: 3, unit: "ea" },
        { name: "Beef patty 60g", qty: 3, unit: "ea" },
      ],
    },
    target: "line",
    target_confidence: "medium",
    rationale: "Dish has no ingredient list on the board yet.",
    model: "hermes",
    status: "pending",
    decided_at: null,
    reject_reason: "",
    task_id: null,
    job_id: 11,
    parse_error: "",
    accept_able: true,
    created_at: new Date(Date.now() - 95 * 60000).toISOString(),
    updated_at: new Date(Date.now() - 95 * 60000).toISOString(),
  },
];

const storageAreas = [
  { id: 1, name: "Walk-in fridge", kind: "fridge" },
  { id: 2, name: "Walk-in freezer", kind: "freezer" },
  { id: 3, name: "Dry store", kind: "store" },
  { id: 7, name: "Skybar cellar", kind: "cellar" },
];

function json(route, body, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify(body),
  });
}

async function stub(page) {
  await page.route(`${API}/**`, async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname.replace("/api/v1", "");

    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, body: "" });
    if (p === "/version") return json(route, { contract_version: "0.1.18", app: "evolving-cook" });
    if (p === "/auth/login" || p === "/auth/refresh") {
      return json(route, { access_token: "stub.token.value", token_type: "bearer", expires_in: 86400 });
    }
    if (p === "/boards/storage-areas") return json(route, storageAreas);
    if (p === "/assist/proposals") return json(route, proposals);
    if (p.startsWith("/boards/days") && p.endsWith("/log")) {
      const section = p.split("/sections/")[1].split("/")[0];
      return json(route, stationLog(section));
    }
    if (p.startsWith("/boards/days") && p.includes("/sections/")) {
      const section = p.split("/sections/")[1].split("/")[0];
      return json(route, boards[section] ?? board(section));
    }
    if (p.startsWith("/boards/days")) return json(route, day);
    if (p === "/sections/settings") return json(route, { sections: [] });
    return json(route, {});
  });
}

const shots = [];

async function shoot(page, name, note) {
  const file = `${OUT}/${name}.png`;
  await page.screenshot({ path: file, fullPage: true });
  shots.push({ name, note, file });
}

const browser = await chromium.launch({ args: ["--no-sandbox", "--disable-dev-shm-usage"] });

// ── Phone (iPhone 14-ish) ────────────────────────────────────────────────
const phone = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
});
const page = await phone.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e?.message || e)));
await stub(page);

await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
await page.waitForTimeout(400);
await shoot(page, "01-login", "LoginPage — first screen every shift");

await page.evaluate(() => {
  localStorage.setItem("ec.access_token", "stub.token.value");
  localStorage.setItem("ec.token_expires_at", String(Date.now() + 86400000));
  localStorage.setItem("evolvingcook.lastStation", "skybar");
});
await page.goto(`${BASE}/#/boards`, { waitUntil: "networkidle" });
await page.waitForTimeout(600);
await shoot(page, "02-choose-station", "BoardsPage — tap 1: day toggle + six section cards");

await page.click("text=Skybar");
await page.waitForTimeout(900);
await shoot(page, "03-station-log", "StationLogPage — tap 2: full log panel before the board");

await page.click("text=Continue to board");
await page.waitForTimeout(900);
await shoot(page, "04-board-skybar-ordering", "BoardPage skybar ordering — tap 3, log panel repeats above the menu");

await page.click("text=Wembley Spritz");
await page.waitForTimeout(500);
await shoot(page, "05-board-line-open", "Expanded ordering row — ingredients, stock dots, 86, note field");

await page.goto(`${BASE}/#/board/${TODAY}/canteen`, { waitUntil: "networkidle" });
await page.waitForTimeout(900);
await shoot(page, "06-board-canteen-counts", "BoardPage canteen counts — three-number rows; qty_draft strip not rendered");

await page.goto(`${BASE}/#/board/${TODAY}/a_la_carte`, { waitUntil: "networkidle" });
await page.waitForTimeout(900);
await shoot(page, "07-mode-prompt", "ModePrompt — the only place section mode can be set");

await page.goto(`${BASE}/#/inbox`, { waitUntil: "networkidle" });
await page.waitForTimeout(900);
await shoot(page, "08-inbox-hidden", "InboxPage — reachable only by typing the hash; no nav entry");

await page.goto(`${BASE}/#/walk`, { waitUntil: "networkidle" });
await page.waitForTimeout(700);
await shoot(page, "09-walk-start", "WalkPage — cold start");

await page.goto(`${BASE}/#/orders`, { waitUntil: "networkidle" });
await page.waitForTimeout(700);
await shoot(page, "10-orders-empty", "OrdersPage — no PO list endpoint, chef types a PO id");

// ── Kitchen iPad (landscape) ─────────────────────────────────────────────
const pad = await browser.newContext({ viewport: { width: 1024, height: 768 }, deviceScaleFactor: 2 });
const padPage = await pad.newPage();
padPage.on("pageerror", (e) => errors.push(String(e?.message || e)));
await stub(padPage);
await padPage.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
await padPage.evaluate(() => {
  localStorage.setItem("ec.access_token", "stub.token.value");
  localStorage.setItem("ec.token_expires_at", String(Date.now() + 86400000));
});
await padPage.goto(`${BASE}/#/board/${TODAY}/skybar`, { waitUntil: "networkidle" });
await padPage.waitForTimeout(900);
const padFile = `${OUT}/11-ipad-board-skybar.png`;
await padPage.screenshot({ path: padFile, fullPage: false });
shots.push({ name: "11-ipad-board-skybar", note: "Same board at 1024×768 — one 40rem column, rest of the glass unused", file: padFile });

await browser.close();

console.log(JSON.stringify({ base: BASE, out: OUT, shots, pageErrors: errors }, null, 2));
