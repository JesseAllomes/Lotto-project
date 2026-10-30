// Auto-entrant for free web-form competitions (m9). Reads data/entries/queue.json (from workers/entry_queue.py),
// fills each entry form with the owner's details and, only when ENTRANT_LIVE=1, submits it.
//
//   node workers/entrant.mjs                 # dry run: fill, screenshot, never submit
//   ENTRANT_LIVE=1 node workers/entrant.mjs  # submit
//
// Owner details come only from environment variables (GitHub secrets): ENTRANT_FIRST_NAME, ENTRANT_LAST_NAME,
// ENTRANT_EMAIL, ENTRANT_PHONE, ENTRANT_POSTCODE, ENTRANT_SUBURB, ENTRANT_STATE, ENTRANT_ADDRESS, ENTRANT_DOB
// (YYYY-MM-DD). They are never written to the log; the log keeps the listing id, the result and which kinds of
// field were filled.
//
// It skips, and logs the reason for, any page with a CAPTCHA or human check, a login, a payment, or a required
// field it cannot fill truthfully. It ticks required consent boxes (terms, age) and leaves optional marketing
// boxes unticked. It makes one attempt per listing per run.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const ENTRIES = path.join(ROOT, "data", "entries");

const EMAIL = ["input[type=email]", "input[name*=mail i]", "input[id*=mail i]", "input[placeholder*=mail i]",
               "input[autocomplete=email]", "input[aria-label*=mail i]"].map((s) => s + ":visible").join(", ");
const OPEN = /^\s*(enter( now| here| today| the (competition|draw|giveaway)| to win)?|click here to enter|get started|start( now)?|join now|i want to win)\s*[!>→]*\s*$/i;

// The first new line of text that reads like an error, with emails and long numbers masked (the log is public).
export function errorLine(pre, post) {
  const seen = new Set(pre.split("\n").map((l) => l.trim()));
  const line = post.split("\n").map((l) => l.trim()).find((l) => l && !seen.has(l) && ERROR.test(l)) || "";
  return line.replace(/[^\s@]+@[^\s@]+/g, "<email>").replace(/\+?\d[\d\s-]{5,}\d/g, "<number>").slice(0, 100);
}

// The form's submit control: a button or link whose text reads like entering, else a submit-type button.
async function submitButton(scope) {
  const cands = scope.locator("button:visible, input[type=submit]:visible, input[type=button]:visible, [role=button]:visible, a.button:visible, a.btn:visible");
  const n = Math.min(await cands.count(), 20);
  let fallback = null;
  for (let i = 0; i < n; i++) {
    const c = cands.nth(i);
    const label = ((await c.innerText().catch(() => "")) || (await c.getAttribute("value")) || (await c.getAttribute("aria-label")) || "").trim();
    if (NOT_SUBMIT.test(label)) continue;
    if (SUBMIT.test(label)) return c;
    if (!fallback && /submit/i.test((await c.getAttribute("type")) || "")) fallback = c;
  }
  return fallback;
}

// Tick a checkbox; styled checkboxes that swallow clicks are set directly, with the events a form listens for.
async function tick(el) {
  try {
    await el.check({ force: true, timeout: 3000 });
  } catch {
    await el.evaluate((e) => {
      e.checked = true;
      e.dispatchEvent(new Event("input", { bubbles: true }));
      e.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
}

// The first frame (the page itself, then embedded frames such as UpViral or Wayin) holding a visible email box.
// When a page has several (a newsletter pop-up, a footer sign-up), the one whose form reads like the competition wins.
async function findEmail(page) {
  let best = null;
  for (const f of page.frames()) {
    try {
      const boxes = f.locator(EMAIL);
      const n = Math.min(await boxes.count(), 6);
      for (let i = 0; i < n; i++) {
        const box = boxes.nth(i);
        const ctx = await box.evaluate((e) => {
          const area = e.closest("form") || e.parentElement?.parentElement?.parentElement || e;
          return { text: (area.innerText || "").slice(0, 2000), footer: !!e.closest("footer"),
                   inputs: area.querySelectorAll("input:not([type=hidden]), select, textarea").length };
        });
        let score = 0;
        if (COMP_WORDS.test(ctx.text)) score += 3;
        if (POPUP_WORDS.test(ctx.text)) score -= 3;
        if (ctx.footer) score -= 2;
        if (ctx.inputs > 2) score += 1;
        if (!best || score > best.score) best = { root: f, box, score };
      }
    } catch { /* frame went away */ }
  }
  return best;
}

// Close cookie banners and pop-ups that sit over the form.
async function dismissOverlays(page) {
  await page.keyboard.press("Escape").catch(() => {});
  const btns = page.locator("button:visible, a:visible, [role=button]:visible").filter({ hasText: DISMISS });
  const n = Math.min(await btns.count().catch(() => 0), 3);
  for (let i = 0; i < n; i++) await btns.nth(0).click({ timeout: 2000 }).catch(() => {});
}
const MARKETING = /newsletter|marketing|offers|subscribe|updates|promotion(al)?|special deals|news and|e-?news|sms (me|updates)/i;
const CONSENT = /terms|conditions|agree|accept|privacy|over 18|18 years|aged? 18|eligib|i confirm|i am/i;
const SUBMIT = /enter|submit|send|\bgo\b|win|register|join|sign ?(me )?up|subscribe|count me in|i'?m in|claim|let'?s go|get started/i;
const NOT_SUBMIT = /terms|conditions|privacy|no,? thanks|close|cancel|log ?in|sign ?in|\bnext\b|unlock|% ?off/i;
const SUCCESS = /thank|thanks|you'?re in|you are in|entered|entry (has been )?(received|submitted|confirmed)|success|good luck|confirm|in the draw|we'?ve got your|see you/i;
const ERROR = /already (been )?(entered|subscribed|registered|signed up)|error|invalid|is required|required field|please (enter|provide|select|check|complete|fill)|try again|not valid/i;
const COMP_WORDS = /enter|competition|giveaway|win|draw|prize|promotion|sweepstake/i;
const POPUP_WORDS = /% ?off|discount|newsletter|unlock|first order|exclusive offers|vip list/i;
const DISMISS = /^\s*(accept( all)?( cookies)?|allow all|i agree|agree|got it|ok|okay|no,? thanks|close|dismiss|×|✕)\s*$/i;

// The owner's number in the four shapes Australian forms ask for: 0412345678, +61412345678, 412345678 and
// 61412345678, whatever shape the secret was typed in.
export function phoneVariants(raw) {
  if (!raw) return null;
  let d = String(raw).replace(/[^\d+]/g, "");
  if (d.startsWith("+61")) d = "0" + d.slice(3);
  else if (d.startsWith("61") && d.length === 11) d = "0" + d.slice(2);
  else if (!d.startsWith("0") && d.length === 9) d = "0" + d;
  const bare = d.replace(/^0/, "");
  return { local: d, intl: "+61" + bare, bare, plain61: "61" + bare };
}

function phoneOrder(v, hint, hasCC) {
  if (hasCC) return [v.bare, v.local, v.intl, v.plain61];
  if (/\+\s?61|\+\d|international|\\\+/.test(hint)) return [v.intl, v.plain61, v.local, v.bare];
  return [v.local, v.intl, v.bare, v.plain61];
}

const COUNTRY = /country|dial|calling|prefix|\bcode\b/i;
const AUSTRALIA = /^\s*(australia|au|aus)\b|\+\s?61\b|\(61\)/i;

export function profile(env = process.env) {
  const p = {
    first: env.ENTRANT_FIRST_NAME, last: env.ENTRANT_LAST_NAME, email: env.ENTRANT_EMAIL, phone: env.ENTRANT_PHONE,
    postcode: env.ENTRANT_POSTCODE, suburb: env.ENTRANT_SUBURB, state: env.ENTRANT_STATE || "VIC",
    address: env.ENTRANT_ADDRESS, dob: env.ENTRANT_DOB,
  };
  if (p.first && p.last) p.full = `${p.first} ${p.last}`;
  return p;
}

// Which owner detail a form field asks for, from its name, id, placeholder, aria-label, autocomplete and label.
export function classify(desc, type) {
  const d = desc.toLowerCase();
  if (type === "password") return "password";
  if (/confirm.*e-?mail|e-?mail.*(confirm|again|repeat)/.test(d)) return "email";
  if (type === "email" || /e-?mail/.test(d)) return "email";
  if (/first|given|fname|forename/.test(d)) return "first";
  if (/last|surname|family|lname/.test(d)) return "last";
  if (/full ?name|your name|^name$|\bname\b/.test(d)) return "full";
  if (type === "tel" || /phone|mobile|\btel\b|contact number/.test(d)) return "phone";
  if (/post ?code|zip/.test(d)) return "postcode";
  if (/suburb|city|town|locality/.test(d)) return "suburb";
  if (/\bstate\b|territory|region/.test(d)) return "state";
  if (/birth|dob|d\.o\.b/.test(d)) return "dob";
  if (/address|street/.test(d)) return "address";
  return null;
}

function dobFor(type, iso) {
  if (!iso) return null;
  const [y, m, dd] = iso.split("-");
  return type === "date" ? iso : `${dd}/${m}/${y}`;
}

// Challenge detection (data/analysis/CAPTCHA_CHECK.md, 2026-10-31): skip only for an interactive challenge a person
// would have to act on, in or attached to the chosen form; invisible/passive checks are submitted and the site decides.
const VENDOR_FRAME = /\/recaptcha\/(api2|enterprise)\/(anchor|bframe)|hcaptcha\.com\/.*hcaptcha\.html|challenges\.cloudflare\.com\//i;
const CUSTOM = "img[src*='captcha' i], img[alt*='captcha' i], img[alt*='security code' i], input[name*='captcha' i], input[id*='captcha' i]";

// Geometry of an element in its own frame; "shown" means a human could see and click it.
const geometry = (e) => {
  const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
  return { w: Math.round(r.width), h: Math.round(r.height),
    shown: r.width >= 100 && r.height >= 40 && r.x > -r.width && r.y > -r.height && cs.visibility !== "hidden" && cs.display !== "none" && cs.opacity !== "0" };
};

// Does `scope` (a Locator for the form, or body) contain the element the frame hangs from? Walks out of shadow roots.
async function inScope(frameEl, scope) {
  const scopeEl = await scope.elementHandle().catch(() => null);
  if (!scopeEl) return false;
  return frameEl.evaluate((el, s) => {
    let host = el;
    for (;;) { const root = host.getRootNode(); if (root instanceof ShadowRoot) host = root.host; else break; }
    return s.contains(host);
  }, scopeEl).catch(() => false);
}

// Returns a reason string when an interactive challenge is in (or attached to) the chosen form, else null.
//   page - Playwright page; root - the frame holding the form; scope - Locator of the form (or that frame's body)
//   opts.tokenWait - how long to give a visible Turnstile to finish its own managed check (ms, default 12000)
export async function interactiveChallenge(page, root, scope, opts = {}) {
  const tokenWait = opts.tokenWait ?? 12000;
  // 1. Custom image/text captchas ("Security code", captcha image) in the form.
  if (await scope.locator(CUSTOM).filter({ visible: true }).count()) return "captcha: security-code field";
  // 2. Vendor widgets, located through their iframes so shadow DOM (Turnstile, Shopify Forms) is covered.
  let turnstileVisible = false;
  for (const f of page.frames()) {
    const url = f.url();
    if (!VENDOR_FRAME.test(url)) continue;
    const el = await f.frameElement().catch(() => null);
    if (!el) continue;
    const parent = f.parentFrame();
    // Only widgets hanging off the form's own frame (or an iframe that itself sits in the form) count.
    let attached = parent === root && (await inScope(el, scope));
    if (!attached && parent && parent.parentFrame() === root) {
      const outer = await parent.frameElement().catch(() => null);
      attached = !!outer && (await inScope(outer, scope));
    }
    if (!attached) continue;
    const g = await el.evaluate(geometry).catch(() => ({ shown: false }));
    if (!g.shown) continue;                                      // invisible/v3/badge/interaction-only: passive, carry on
    const size = (() => { try { return new URL(url).searchParams.get("size") || ""; } catch { return ""; } })();
    if (/\/recaptcha\//.test(url)) {
      if (/anchor/.test(url) && size !== "invisible") return "captcha: reCAPTCHA v2 checkbox";
      if (/bframe/.test(url)) return "captcha: reCAPTCHA challenge open";
      continue;                                                  // visible v3/invisible badge: passive
    }
    if (/hcaptcha/.test(url)) return "captcha: hCaptcha checkbox";
    if (/challenges\.cloudflare/.test(url)) turnstileVisible = true;
  }
  // 3. A visible Turnstile widget is interactive only if its managed check does not complete by itself.
  if (turnstileVisible) {
    const token = scope.locator("[name='cf-turnstile-response']");
    const deadline = Date.now() + tokenWait;
    while (Date.now() < deadline) {
      const vals = await token.evaluateAll((els) => els.map((e) => e.value || "")).catch(() => []);
      if (vals.some((v) => v.length > 20)) return null;          // passed on its own: no interaction needed
      await page.waitForTimeout(500);
    }
    return "captcha: Turnstile awaiting interaction";
  }
  // 4. Visible "I'm not a robot" host without an iframe we could map (defensive).
  if (await scope.locator(".g-recaptcha:not([data-size='invisible']), .h-captcha:not([data-size='invisible'])").filter({ visible: true })
        .filter({ has: root.locator("iframe") }).count()) return "captcha: visible checkbox widget";
  return null;
}

// Post-submit: a challenge the site opened after the click (reCAPTCHA bframe pop-up, hCaptcha challenge, Turnstile, Shopify /challenge).
export async function challengeAfterSubmit(page) {
  if (/\/challenge\b/.test(new URL(page.url()).pathname)) return "captcha: /challenge page";
  if (/just a moment|attention required/i.test(await page.title().catch(() => ""))) return "captcha: interstitial";
  for (const f of page.frames()) {
    if (!VENDOR_FRAME.test(f.url())) continue;
    if (/\/recaptcha\/.*anchor/.test(f.url())) continue;         // the anchor/badge is never a challenge by itself
    const el = await f.frameElement().catch(() => null);
    const g = el ? await el.evaluate(geometry).catch(() => ({ shown: false })) : { shown: false };
    if (g.shown) return "captcha: challenge opened after submit";
  }
  return null;
}

// A Cloudflare/hCaptcha interstitial in front of the whole page (gleam.io and the like), not a form widget.
async function interstitial(page) {
  if (/just a moment|attention required/i.test(await page.title().catch(() => ""))) return true;
  if (/complete this security check to access/i.test(await page.locator("body").innerText().catch(() => ""))) return true;
  for (const f of page.frames()) {
    if (!/challenges\.cloudflare\.com\/|hcaptcha\.com\/.*hcaptcha\.html/i.test(f.url())) continue;
    const el = await f.frameElement().catch(() => null);
    if (el && (await el.evaluate(geometry).catch(() => ({ shown: false }))).shown) return true;
  }
  return false;
}

// Fill one form. Returns {result, reason, fields} without any of the owner's values.
export async function fillForm(page, item, who, live) {
  if (await page.locator("input[type=password]:visible").count()) return { result: "skipped", reason: "login", fields: [] };
  if (await page.locator("input[autocomplete^=cc-]:visible, input[name*=card i]:visible, input[id*=cardnumber i]:visible").count()) {
    return { result: "skipped", reason: "payment", fields: [] };
  }
  await dismissOverlays(page);
  let found = await findEmail(page);
  if (!found) {                                   // late-loading forms
    await page.waitForTimeout(5000);
    found = await findEmail(page);
  }
  if (!found) {                                   // forms behind an "Enter now" button
    const opener = page.locator("a:visible, button:visible").filter({ hasText: OPEN }).first();
    if (await opener.count()) {
      await opener.click({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(4000);
      found = await findEmail(page);
    }
  }
  if (!found) return { result: "skipped", reason: (await interstitial(page)) ? "blocked" : "no_form", fields: [] };
  const { root, box: emailBox } = found;
  if (await root.locator("input[type=password]:visible").count()) return { result: "skipped", reason: "login", fields: [] };
  const form = root.locator("form").filter({ has: emailBox }).first();
  const scope = (await form.count()) ? form : root.locator("body");
  const filled = new Set();
  const hasCC = await scope.locator("select:visible").evaluateAll((els) => els.some((e) =>
    /country|dial|calling|prefix|code/i.test([e.name, e.id, e.getAttribute("aria-label")].join(" ")) &&
    [...e.options].some((o) => /\+\s?61\b|\(61\)/.test(o.text + " " + o.value))));
  const controls = scope.locator("input:visible, select:visible, textarea:visible");
  const n = await controls.count();
  for (let i = 0; i < n; i++) {
    const el = controls.nth(i);
    const info = await el.evaluate((e) => {
      const lab = (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) || e.closest("label");
      return {
        tag: e.tagName.toLowerCase(), type: (e.getAttribute("type") || "").toLowerCase(),
        required: e.required || e.getAttribute("aria-required") === "true",
        desc: [e.name, e.id, e.placeholder, e.getAttribute("aria-label"), e.getAttribute("autocomplete"),
               lab ? lab.innerText : ""].filter(Boolean).join(" "),
        hint: [e.placeholder, e.getAttribute("pattern"), e.getAttribute("title")].filter(Boolean).join(" "),
        options: e.tagName === "SELECT" ? [...e.options].map((o) => o.text + "|" + o.value) : [],
      };
    });
    if (["hidden", "submit", "button", "image", "reset", "file"].includes(info.type)) {
      if (info.type === "file" && info.required) return { result: "skipped", reason: "unfillable", fields: ["file"] };
      continue;
    }
    if (info.type === "checkbox" || info.type === "radio") {
      if (info.type === "checkbox" && CONSENT.test(info.desc) && !MARKETING.test(info.desc)) {
        await tick(el);
        filled.add("consent");
      } else if (info.required && info.type === "checkbox" && !MARKETING.test(info.desc)) {
        return { result: "skipped", reason: "unfillable", fields: [`required checkbox: ${info.desc.slice(0, 60)}`] };
      } else if (info.required && info.type === "checkbox") {
        await tick(el);           // marketing box the form will not submit without
        filled.add("required_marketing");
      }
      continue;
    }
    if (info.tag === "textarea" || (info.type === "text" && /answer|why|tell us|words|response|question/i.test(info.desc))) {
      if (item.answer) {
        await el.fill(item.answer);
        filled.add("answer");
        continue;
      }
      if (info.required) return { result: "skipped", reason: "needs_answer", fields: [] };
      continue;
    }
    const kind = classify(info.desc, info.type);
    if (info.tag === "select") {
      if (kind === "state") {
        const opt = info.options.find((o) => /^(vic|victoria)\b/i.test(o)) ;
        if (opt) { await el.selectOption({ value: opt.split("|")[1] }); filled.add("state"); continue; }
      }
      if (COUNTRY.test(info.desc) || info.options.filter((o) => AUSTRALIA.test(o)).length) {
        const opt = info.options.find((o) => AUSTRALIA.test(o.split("|")[0])) || info.options.find((o) => AUSTRALIA.test(o));
        if (opt) { await el.selectOption({ value: opt.split("|")[1] }); filled.add("country"); continue; }
      }
      if (info.required) return { result: "skipped", reason: "unfillable", fields: [`select: ${info.desc.slice(0, 60)}`] };
      continue;
    }
    if (kind === "phone" && who.phone) {
      const tries = phoneOrder(phoneVariants(who.phone), info.hint + " " + info.desc, hasCC);
      for (const v of tries) {
        await el.fill(v);
        if (await el.evaluate((e) => e.checkValidity())) break;
      }
      filled.add("phone");
      continue;
    }
    const value = kind === "dob" ? dobFor(info.type, who.dob) : kind ? who[kind] : null;
    if (value) {
      await el.fill(String(value));
      filled.add(kind);
    } else if (info.required) {
      return { result: "skipped", reason: "unfillable", fields: [kind || info.desc.slice(0, 60)] };
    }
  }
  if (!filled.has("email")) return { result: "skipped", reason: "unfillable", fields: ["email"] };
  const why = await interactiveChallenge(page, root, scope);
  if (why) return { result: "skipped", reason: "captcha", fields: [...filled], said: why };
  if (!live) {
    const t = await submitButton(scope);
    const label = t ? ((await t.innerText().catch(() => "")) || (await t.getAttribute("value")) || "submit").trim().slice(0, 30) : "";
    return { result: "dry_ok", reason: t ? `would click "${label}"` : "no submit button", fields: [...filled] };
  }
  const before = page.url();
  const textNow = async () => (await page.locator("body").innerText().catch(() => "")) +
    (root !== page.mainFrame() ? " " + (await root.locator("body").innerText().catch(() => "")) : "");
  const count = (re, t) => (t.match(new RegExp(re.source, "gi")) || []).length;
  const pre = await textNow();
  const target = await submitButton(scope);
  if (target) {
    try {
      await target.click({ timeout: 8000 });
    } catch {
      await dismissOverlays(page);
      try { await target.click({ timeout: 5000 }); } catch { await target.evaluate((e) => e.click()); }
    }
  } else {
    const formEl = scope.locator("xpath=self::form");
    if (!(await formEl.count())) return { result: "skipped", reason: "no_submit", fields: [...filled] };
    await formEl.evaluate((f) => (f.requestSubmit ? f.requestSubmit() : f.submit()));
  }
  await page.waitForTimeout(8000);
  const post = await textNow();
  const after = await challengeAfterSubmit(page);
  if (after) return { result: "skipped", reason: "captcha", fields: [...filled], said: after };   // e.g. Shopify /challenge
  const err = post.match(new RegExp(ERROR.source, "i"));
  if (err && /already/i.test(err[0])) return { result: "entered", reason: "already entered", fields: [...filled] };
  if (page.url() !== before || count(SUCCESS, post) > count(SUCCESS, pre)) return { result: "entered", reason: "", fields: [...filled] };
  if (err && count(ERROR, post) > count(ERROR, pre)) {
    const said = errorLine(pre, post);
    if (/blocked|suspicious|unusual|robot|automated|verify you are human/i.test(said)) {
      return { result: "skipped", reason: "human_check", fields: [...filled], said };   // anti-bot rejection
    }
    return { result: "failed", reason: `form said: ${err[0].toLowerCase()}`, fields: [...filled], said };
  }
  const gone = !(await emailBox.isVisible().catch(() => false)) || !(await emailBox.inputValue().catch(() => ""));
  if (gone) return { result: "entered", reason: "form cleared", fields: [...filled] };
  return { result: "failed", reason: "no confirmation seen", fields: [...filled] };
}

// Forms are filled CONCURRENCY at a time, each in its own browser context (separate cookies), so a round of 50
// comps takes minutes, not a quarter of an hour; results keep the queue's order. Pacing between entries to the
// same comp is entry_queue's job and is unchanged.
const CONCURRENCY = Math.max(1, +(process.env.ENTRANT_CONCURRENCY || 6));

export async function run({ queue, live = process.env.ENTRANT_LIVE === "1", max = 200, shots = process.env.ENTRANT_SHOTS,
                            logPath = process.env.ENTRANT_LOG || path.join(ENTRIES, "log.jsonl"), launch,
                            concurrency = CONCURRENCY } = {}) {
  const who = profile();
  if (!who.email || !who.first || !who.last) throw new Error("owner details missing: set the ENTRANT_* secrets");
  const qfile = process.env.ENTRANT_QUEUE || path.join(ENTRIES, "queue.json");
  const items = (queue ?? JSON.parse(fs.readFileSync(qfile, "utf8"))).slice(0, max);
  const { chromium } = require("playwright");
  const browser = await (launch ? launch() : chromium.launch());
  const out = new Array(items.length);
  let next = 0;
  async function one(item) {
    const context = await browser.newContext();
    const page = await context.newPage();
    let r;
    try {
      await page.goto(item.entry_url, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForTimeout(2500);
      r = await fillForm(page, item, who, live);
      if (shots) await page.screenshot({ path: path.join(shots, `${item.id}.png`), fullPage: true });
    } catch (e) {
      r = { result: "failed", reason: String(e.message || e).split("\n")[0].slice(0, 120), fields: [] };
    } finally {
      await context.close().catch(() => {});
    }
    const rec = { time_utc: new Date().toISOString().slice(0, 19) + "Z", id: item.id, mode: live ? "live" : "dry", ...r };
    fs.appendFileSync(logPath, JSON.stringify(rec) + "\n");
    console.log(`${rec.id}: ${rec.result}${rec.reason ? " (" + rec.reason + ")" : ""}`);
    return rec;
  }
  try {
    await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
      while (next < items.length) {
        const i = next++;
        out[i] = await one(items[i]);
      }
    }));
  } finally {
    await browser.close();
  }
  return out;
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  run().catch((e) => { console.error(e.message); process.exit(1); });
}
