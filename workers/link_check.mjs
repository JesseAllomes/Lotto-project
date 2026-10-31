// Open every open listing's entry link in a real browser and check that the page is that competition.
//
//   NODE_PATH=... node workers/link_check.mjs            # reads data/comps/link_targets.json (workers/entry_pages.py)
//
// A plain fetch sees only the HTML a server sends, and many competition pages build their content with JavaScript, so
// this loads each page in headless Chromium, waits for it to settle, and reads the visible text (frames included).
// Results, one per listing, appended to data/comps/link_checks.jsonl:
//   dead     the page is not found (404/410) or the browser cannot load it at all
//   home     it lands on the site's home page and says nothing about the competition
//   blocked  a bot wall or "just a moment" interstitial; nothing to read
//   login    the page asks to log in before it shows anything (social posts, members' areas)
//   wrong    the page loads but names neither the brand nor the prize: probably not this competition
//   ok       the page names the brand or the prize, and talks about a competition
// Nothing is filled in or submitted; no personal details are used.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const TARGETS = process.env.LINK_TARGETS || path.join(ROOT, "data", "comps", "link_targets.json");
const OUT = process.env.LINK_OUT || path.join(ROOT, "data", "comps", "link_checks.jsonl");
const CONCURRENCY = +(process.env.LINK_CONCURRENCY || 12);
const COMP = /\b(win|winner|competition|giveaway|give-away|prize|enter|entries|entry|promotion|sweepstake|draw|chance)\b/gi;
const WALL = /just a moment|attention required|verify you are human|access denied|checking your browser|request blocked/i;
const LOGIN = /log ?in|sign ?in|create (an )?account|password/i;

// Words that identify this listing: the brand's words and the prize's nouns (the title without "win", numbers, filler).
const STOP = new Set(("win a an the of to for and with your you our in on at by from or + & 1 2 3 4 5 x worth valued " +
  "prize prizes pack package packs set bundle voucher vouchers gift card cards competition giveaway chance " +
  "trip double pass passes one two three four five six ten new ultimate").split(" "));
export function keys(item) {
  const words = (s) => (s || "").toLowerCase().replace(/[’']/g, "").match(/[a-z][a-z0-9-]{2,}/g) || [];
  const brand = words(item.brand).filter((w) => !STOP.has(w));
  const prize = words(item.title.replace(/^[^–-]*[–-]\s*/, (m) => (item.brand && m.toLowerCase().includes(item.brand.toLowerCase().slice(0, 5)) ? "" : m)))
    .filter((w) => !STOP.has(w) && !/^\d/.test(w));
  return { brand: [...new Set(brand)], prize: [...new Set(prize)] };
}

export function verdict({ status, finalUrl, startUrl, text, title, form = false }, item) {
  if (status === 404 || status === 410 || status === 0) return { kind: "dead" };
  const body = `${title || ""} ${text || ""}`;
  if (WALL.test(title || "") || (text.length < 400 && WALL.test(text))) return { kind: "blocked" };
  const low = body.toLowerCase();
  const k = keys(item);
  const brandHit = k.brand.filter((w) => low.includes(w));
  const prizeHit = k.prize.filter((w) => low.includes(w));
  const matched = [...brandHit, ...prizeHit];
  const comp = (body.match(COMP) || []).length;
  const contest = (body.match(/\b(win|giveaway|competition|sweepstakes?|prize draw|enter now|entries close)\b/gi) || []).length;
  const now = new URL(finalUrl);
  const compUrl = /win|comp|giveaway|promo|contest|sweep|prize|draw/i.test(now.hostname + now.pathname);
  // a bare home page (where the link starts or ends) with no competition on it
  if (!now.pathname.replace(/\/+$/, "") && !now.search.replace(/^\?showwelcome$/, "") && contest < 2) return { kind: "home", matched };
  if (text.length < 600 && LOGIN.test(body) && comp < 2) return { kind: "login", matched };
  const named = brandHit.length > 0 || prizeHit.length >= Math.min(2, k.prize.length || 1);
  if (named && (comp >= 2 || form || compUrl)) return { kind: "ok", matched };
  return { kind: "wrong", matched };
}

async function visit(browser, item) {
  const context = await browser.newContext({ locale: "en-AU", timezoneId: "Australia/Melbourne" });
  const page = await context.newPage();
  const rec = { id: item.id, checked_utc: new Date().toISOString().slice(0, 19) + "Z", url: item.entry_url };
  try {
    const resp = await page.goto(item.entry_url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForLoadState("networkidle", { timeout: 6000 }).catch(() => {});
    await page.waitForTimeout(1000);
    const texts = [];
    for (const f of page.frames()) texts.push(await f.locator("body").innerText({ timeout: 3000 }).catch(() => ""));
    const text = texts.join(" ").replace(/\s+/g, " ");
    let form = false;
    for (const f of page.frames()) form = form || (await f.locator("input[type=email], input[name*=mail i], textarea").count().catch(() => 0)) > 0;
    const info = { status: resp ? resp.status() : 0, finalUrl: page.url(), startUrl: item.entry_url, text, form,
                   title: await page.title().catch(() => "") };
    Object.assign(rec, { status: info.status, final: info.finalUrl, form, ...verdict(info, item) });
  } catch (e) {
    const msg = String(e.message || e);
    rec.kind = /ERR_NAME_NOT_RESOLVED|ERR_CONNECTION_REFUSED|ERR_ADDRESS_UNREACHABLE/.test(msg) ? "dead" : "error";
    rec.error = msg.split("\n")[0].slice(0, 120);
  } finally {
    await context.close().catch(() => {});
  }
  return rec;
}

// Pages checked within the last RECHECK_DAYS are skipped (the daily run then only does new and stale ones).
const RECHECK_DAYS = 3;
function fresh(out) {
  const done = new Set();
  if (!fs.existsSync(out)) return done;
  const since = Date.now() - RECHECK_DAYS * 864e5;
  for (const l of fs.readFileSync(out, "utf8").split("\n")) {
    if (!l.trim()) continue;
    const r = JSON.parse(l);
    if (r.kind !== "error" && Date.parse(r.checked_utc) >= since) done.add(r.id);
  }
  return done;
}

export async function run(items = JSON.parse(fs.readFileSync(TARGETS, "utf8")), out = OUT) {
  const done = fresh(out);
  items = items.filter((i) => !done.has(i.id));
  const { chromium } = require("playwright");
  const browser = await chromium.launch();
  let next = 0;
  const counts = {};
  try {
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, items.length) }, async () => {
      while (next < items.length) {
        const rec = await visit(browser, items[next++]);
        counts[rec.kind] = (counts[rec.kind] || 0) + 1;
        fs.appendFileSync(out, JSON.stringify(rec) + "\n");
      }
    }));
  } finally {
    await browser.close();
  }
  console.log(`link_check: ${items.length} pages: ` + Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", "));
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  run().catch((e) => { console.error(e.message); process.exit(1); });
}
