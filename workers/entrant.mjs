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

export const CAPTCHA = /recaptcha|hcaptcha|turnstile|challenges\.cloudflare|captcha|are you (a )?human|verify you are human/i;
const MARKETING = /newsletter|marketing|offers|subscribe|updates|promotion(al)?|special deals|news and|e-?news|sms (me|updates)/i;
const CONSENT = /terms|conditions|agree|accept|privacy|over 18|18 years|aged? 18|eligib|i confirm|i am/i;
const SUBMIT = /enter|submit|send|go|win|register|join|i'?m in|count me in/i;
const SUCCESS = /thank|thanks|you'?re in|entered|entry (has been )?(received|submitted|confirmed)|success|good luck|confirm/i;

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

// Fill one form. Returns {result, reason, fields} without any of the owner's values.
export async function fillForm(page, item, who, live) {
  const html = await page.content();
  const frames = page.frames().map((f) => f.url()).join(" ");
  if (CAPTCHA.test(frames) || /class="[^"]*(g-recaptcha|h-captcha|cf-turnstile)/i.test(html)) {
    return { result: "skipped", reason: "captcha", fields: [] };
  }
  if (await page.locator("input[type=password]:visible").count()) return { result: "skipped", reason: "login", fields: [] };
  if (await page.locator("input[autocomplete^=cc-]:visible, input[name*=card i]:visible, input[id*=cardnumber i]:visible").count()) {
    return { result: "skipped", reason: "payment", fields: [] };
  }
  const emailBox = page.locator("input[type=email]:visible, input[name*=mail i]:visible, input[id*=mail i]:visible").first();
  if (!(await emailBox.count())) return { result: "skipped", reason: "no_form", fields: [] };
  const form = page.locator("form").filter({ has: emailBox }).first();
  const scope = (await form.count()) ? form : page.locator("body");
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
        await el.check({ force: true });
        filled.add("consent");
      } else if (info.required && info.type === "checkbox" && !MARKETING.test(info.desc)) {
        return { result: "skipped", reason: "unfillable", fields: [`required checkbox: ${info.desc.slice(0, 60)}`] };
      } else if (info.required && info.type === "checkbox") {
        await el.check({ force: true });           // marketing box the form will not submit without
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
  if (!live) return { result: "dry_ok", reason: "", fields: [...filled] };
  const before = page.url();
  const button = scope.locator("button:visible, input[type=submit]:visible").filter({ hasText: SUBMIT }).first();
  const target = (await button.count()) ? button : scope.locator("button[type=submit]:visible, input[type=submit]:visible").first();
  if (!(await target.count())) return { result: "skipped", reason: "no_submit", fields: [...filled] };
  await target.click();
  await page.waitForTimeout(8000);
  const after = await page.locator("body").innerText();
  if (CAPTCHA.test(page.frames().map((f) => f.url()).join(" "))) return { result: "skipped", reason: "captcha", fields: [...filled] };
  const ok = page.url() !== before || SUCCESS.test(after);
  return { result: ok ? "entered" : "failed", reason: ok ? "" : "no confirmation seen", fields: [...filled] };
}

export async function run({ queue, live = process.env.ENTRANT_LIVE === "1", max = 40, shots = process.env.ENTRANT_SHOTS,
                            logPath = path.join(ENTRIES, "log.jsonl"), launch } = {}) {
  const who = profile();
  if (!who.email || !who.first || !who.last) throw new Error("owner details missing: set the ENTRANT_* secrets");
  const items = (queue ?? JSON.parse(fs.readFileSync(path.join(ENTRIES, "queue.json"), "utf8"))).slice(0, max);
  const { chromium } = require("playwright");
  const browser = await (launch ? launch() : chromium.launch());
  const out = [];
  try {
    for (const item of items) {
      const page = await browser.newPage();
      let r;
      try {
        await page.goto(item.entry_url, { waitUntil: "domcontentloaded", timeout: 45000 });
        await page.waitForTimeout(2500);
        r = await fillForm(page, item, who, live);
        if (shots) await page.screenshot({ path: path.join(shots, `${item.id}.png`), fullPage: true });
      } catch (e) {
        r = { result: "failed", reason: String(e.message || e).split("\n")[0].slice(0, 120), fields: [] };
      } finally {
        await page.close();
      }
      const rec = { time_utc: new Date().toISOString().slice(0, 19) + "Z", id: item.id, mode: live ? "live" : "dry", ...r };
      fs.appendFileSync(logPath, JSON.stringify(rec) + "\n");
      out.push(rec);
      console.log(`${rec.id}: ${rec.result}${rec.reason ? " (" + rec.reason + ")" : ""}`);
    }
  } finally {
    await browser.close();
  }
  return out;
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  run().catch((e) => { console.error(e.message); process.exit(1); });
}
