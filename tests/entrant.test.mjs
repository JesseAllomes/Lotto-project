// Offline tests for workers/entrant.mjs on local HTML forms (node --test tests/entrant.test.mjs). Fake details only.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { classify, phoneVariants, run } from "../workers/entrant.mjs";

const FORMS = path.join(path.dirname(new URL(import.meta.url).pathname), "fixtures", "forms");
const url = (f) => "file://" + path.join(FORMS, f);
Object.assign(process.env, {
  ENTRANT_FIRST_NAME: "Test", ENTRANT_LAST_NAME: "Person", ENTRANT_EMAIL: "test.person@example.com",
  ENTRANT_PHONE: "0400000000", ENTRANT_POSTCODE: "3000", ENTRANT_STATE: "VIC", ENTRANT_DOB: "1980-01-02",
});

function tmpLog() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "entrant-")), "log.jsonl");
}

test("field classification", () => {
  assert.equal(classify("first_name fn First name", "text"), "first");
  assert.equal(classify("email Email", "email"), "email");
  assert.equal(classify("confirm_email Confirm your email", "text"), "email");
  assert.equal(classify("Your name", "text"), "full");
  assert.equal(classify("mobile", "tel"), "phone");
  assert.equal(classify("Postcode", "text"), "postcode");
  assert.equal(classify("store_location Favourite store location", "text"), null);
});

test("dry run fills a plain form, ticks consent, leaves marketing, never submits", async () => {
  const logPath = tmpLog();
  const [r] = await run({ queue: [{ id: 1, entry_url: url("simple.html") }], live: false, logPath });
  assert.equal(r.result, "dry_ok");
  assert.equal(r.reason, 'would click "Enter now"');
  assert.deepEqual([...r.fields].sort(), ["consent", "email", "first", "last", "phone", "postcode", "state"]);
  const log = fs.readFileSync(logPath, "utf8");
  assert.ok(!log.includes("example.com") && !log.includes("0400000000") && !log.includes("Person"));
});

test("live run submits and sees the confirmation", async () => {
  const [r] = await run({ queue: [{ id: 2, entry_url: url("simple.html") }], live: true, logPath: tmpLog() });
  assert.equal(r.result, "entered");
});

test("captcha and unknown required fields are skipped with a reason", async () => {
  const out = await run({ queue: [{ id: 3, entry_url: url("captcha.html") }, { id: 4, entry_url: url("unknown_required.html") }],
                          live: true, logPath: tmpLog() });
  assert.deepEqual(out.map((r) => [r.result, r.reason]), [["skipped", "captcha"], ["skipped", "unfillable"]]);
});

test("skill form needs an approved answer, and uses it when given", async () => {
  const [a] = await run({ queue: [{ id: 5, entry_url: url("skill.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([a.result, a.reason], ["skipped", "needs_answer"]);
  const [b] = await run({ queue: [{ id: 5, entry_url: url("skill.html"), answer: "Approved words." }], live: true, logPath: tmpLog() });
  assert.equal(b.result, "entered");
  assert.ok(b.fields.includes("answer"));
});

test("phone number shapes", () => {
  const want = { local: "0412345678", intl: "+61412345678", bare: "412345678", plain61: "61412345678" };
  for (const typed of ["0412 345 678", "+61 412 345 678", "61412345678", "412345678"]) {
    assert.deepEqual(phoneVariants(typed), want);
  }
});

test("phone is entered in the shape each form wants (+61, country-code dropdown, local)", async () => {
  const out = await run({ queue: ["phone_intl.html", "phone_cc.html", "phone_local.html"].map((f, i) => ({ id: 10 + i, entry_url: url(f) })),
                          live: true, logPath: tmpLog() });
  assert.deepEqual(out.map((r) => r.result), ["entered", "entered", "entered"]);
  assert.ok(out[1].fields.includes("country"));
});

test("forms inside frames and behind an Enter button are found", async () => {
  const out = await run({ queue: [{ id: 20, entry_url: url("iframe_outer.html") }, { id: 21, entry_url: url("behind_button.html") }],
                          live: true, logPath: tmpLog() });
  assert.deepEqual(out.map((r) => r.result), ["entered", "entered"]);
});

test("picks the competition form over a discount pop-up and a footer sign-up; JS button; form hides on success", async () => {
  const [r] = await run({ queue: [{ id: 30, entry_url: url("popup_and_comp.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([r.result, r.reason], ["entered", "form cleared"]);
});

test("Mantine-style forms: untyped answer box, label-marked required, State and dial-code pickers", async () => {
  const [r] = await run({ queue: [{ id: 50, entry_url: url("mantine.html"), answer: "A test answer" }], live: true, logPath: tmpLog() });
  assert.equal(r.result, "entered", JSON.stringify(r));
  for (const f of ["answer", "state", "phone", "email"]) assert.ok(r.fields.includes(f), f);
});

test("a 'captcha validation failed' reply is the site's bot check: skipped, not retried", async () => {
  const [r] = await run({ queue: [{ id: 51, entry_url: url("captcha_rejected.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([r.result, r.reason], ["skipped", "captcha"]);
});

test("an 'already entered' reply counts as entered once", async () => {
  const [r] = await run({ queue: [{ id: 31, entry_url: url("already.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([r.result, r.reason], ["entered", "already entered"]);
});

test("a bounce to a /challenge page is a captcha; a 'try again' reply is a failure with what the form said", async () => {
  const out = await run({ queue: [{ id: 40, entry_url: url("shopify_challenge.html") }, { id: 41, entry_url: url("rejected.html") }],
                          live: true, logPath: tmpLog() });
  assert.deepEqual(out.map((r) => r.result), ["skipped", "failed"]);
  assert.equal(out[0].reason, "captcha");
  assert.match(out[1].said, /try again/);
});

// Challenge detection (data/analysis/CAPTCHA_CHECK.md): vendor iframes are stubbed, nothing leaves the machine.
const SHELL = (inner, after = "") => `<html><body><form id="comp" action="/enter"><h2>Win a prize</h2>
  <input name="first" placeholder="First name"><input type="email" name="email" placeholder="Email">${inner}
  <button>Enter now</button></form>${after}</body></html>`;
const ANCHOR = (size, w = 304, h = 78) => `<iframe title="reCAPTCHA" src="https://www.google.com/recaptcha/api2/anchor?ar=1&k=6LTEST&hl=en&size=${size}" width="${w}" height="${h}"></iframe>`;
const TURNSTILE = (value, w = 300, h = 65) => `<div class="cf-turnstile" style="width:${w}px;height:${h}px"><iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/f/av0/rch/abc/0x4TEST" width="${w}" height="${h}"></iframe></div><input type="hidden" name="cf-turnstile-response" value="${value}">`;
const HC = (w, h) => `<div class="h-captcha"${w ? "" : ' data-size="invisible" style="height:0"'}><iframe src="https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=checkbox" width="${w}" height="${h}"></iframe></div>`;
const CASES = [
  ["visible reCAPTCHA v2 checkbox in the form", SHELL(`<div class="g-recaptcha">${ANCHOR("normal")}</div>`), "captcha: reCAPTCHA v2 checkbox"],
  ["invisible reCAPTCHA badge outside the form", SHELL('<input type="hidden" name="g-recaptcha-response">',
    `<div class="grecaptcha-badge" style="position:fixed;bottom:14px;right:-186px;width:256px;height:60px">${ANCHOR("invisible", 256, 60)}</div>`), null],
  ["visible Turnstile with no token", SHELL(TURNSTILE("")), "captcha: Turnstile awaiting interaction"],
  ["Turnstile that has issued its token", SHELL(TURNSTILE("0.ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef")), null],
  ["interaction-only Turnstile with a 0-height host", SHELL(TURNSTILE("", 300, 0)), null],
  ["visible v2 widget on another form", SHELL(""), null],
  ["custom security-code image", SHELL('<img alt="security code" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="120" height="40"><input name="cp_captcha">'), "captcha: security-code field"],
  ["invisible hCaptcha in the form", SHELL(HC(0, 0)), null],
  ["visible hCaptcha checkbox in the form", SHELL(HC(303, 78)), "captcha: hCaptcha checkbox"],
];
CASES[5][1] = CASES[5][1].replace("</body>", `<footer><form action="/newsletter"><input type="email" name="EMAIL"><div class="g-recaptcha">${ANCHOR("normal")}</div></form></footer></body>`);

test("only an interactive challenge on the chosen form is a captcha; invisible or passive checks are not", async () => {
  const { interactiveChallenge, challengeAfterSubmit } = await import("../workers/entrant.mjs");
  const { chromium } = createRequire(import.meta.url)("playwright");    // NODE_PATH, as the entrant loads it
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route(/^https:\/\//, (r) => r.fulfill({ contentType: "text/html", body: "<html><body></body></html>" }));
    for (const [name, html, want] of CASES) {
      await page.setContent(html);
      await page.waitForTimeout(300);
      const scope = page.locator("form#comp");
      assert.equal(await interactiveChallenge(page, page.mainFrame(), scope, { tokenWait: 1000 }), want, name);
    }
    await page.setContent(`<html><body>${ANCHOR("invisible", 256, 60)}</body></html>`);
    assert.equal(await challengeAfterSubmit(page), null, "anchor alone after submit");
    await page.setContent('<html><body><iframe src="https://www.google.com/recaptcha/api2/bframe?k=x" width="400" height="580"></iframe></body></html>');
    await page.waitForTimeout(300);
    assert.equal(await challengeAfterSubmit(page), "captcha: challenge opened after submit");
  } finally {
    await browser.close();
  }
});

test("error lines are masked before logging", async () => {
  const { errorLine } = await import("../workers/entrant.mjs");
  assert.equal(errorLine("a\nb", "a\nb\nError: jo@x.com already used, call 0412 345 678"), "Error: <email> already used, call <number>");
});

// Fixes from data/analysis/ENTRY_ERRORS.md (Fable's audit of run 41141359948).
test("underscored names and John Doe placeholders classify as names", () => {
  assert.equal(classify("sw__login_name John Doe", "text"), "full");
  assert.equal(classify("contact[first-name]", "text"), "first");
  assert.equal(classify("store_location Favourite store location", "text"), null);
});

test("SweepWidget-style login (no <form>, Full Name box named sw__login_name) is filled and counts as entered", async () => {
  const [r] = await run({ queue: [{ id: 1, entry_url: url("sweepwidget.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([r.result, r.reason], ["entered", "form cleared"]);
  assert.ok(r.fields.includes("full") && r.fields.includes("email"));
});

test("a page whose only email box is a footer newsletter has no entry form", async () => {
  const [r] = await run({ queue: [{ id: 2, entry_url: url("footer_only.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([r.result, r.reason], ["skipped", "no_form"]);
});

test("a form that appears 9 s after load is still found", async () => {
  const [r] = await run({ queue: [{ id: 3, entry_url: url("late_embed.html") }], live: false, logPath: tmpLog() });
  assert.deepEqual([r.result, r.reason], ["dry_ok", 'would click "Enter now"']);
});

test("Umbraco-style GUID fields: the Email label is found, the Organisation box stops the entry", async () => {
  const [r] = await run({ queue: [{ id: 4, entry_url: url("umbraco.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([r.result, r.reason], ["skipped", "unfillable"]);
  assert.match(r.fields[0], /Organisation/);
});

test("no-form sub-reasons: moved (redirected elsewhere on the site), login (hidden member modal), blocked (embed interstitial)", async () => {
  const out = await run({ queue: [{ id: 5, entry_url: url("moved_from.html") }, { id: 6, entry_url: url("login_wall.html") },
                                  { id: 7, entry_url: url("gleam_blocked.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual(out.map((r) => [r.result, r.reason]), [["skipped", "moved"], ["skipped", "login"], ["skipped", "blocked"]]);
});

test("a Klaviyo form's generic submit error is the vendor's bot check: manual list, not a retry", async () => {
  const [r] = await run({ queue: [{ id: 8, entry_url: url("klaviyo_error.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([r.result, r.reason], ["skipped", "human_check"]);
  assert.match(r.said, /^klaviyo: An error occurred when submitting/);
});

test("a terms page that names the entry page leads there; 'Prefer not to say' answers the gender box; the answer box needs the owner", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "terms-"));
  const terms = path.join(dir, "terms.html");
  fs.writeFileSync(terms, `<html><body><h1>Giveaway Terms</h1><p>5) How to Enter. No purchase is necessary. To enter the Promotion, visit: ${url("wf_entry.html")} (Australian residents) during the Promotion Period.</p></body></html>`);
  const [a] = await run({ queue: [{ id: 9, entry_url: "file://" + terms }], live: true, logPath: tmpLog() });
  assert.deepEqual([a.result, a.reason], ["skipped", "needs_answer"]);
  const [b] = await run({ queue: [{ id: 9, entry_url: "file://" + terms, answer: "Approved words." }], live: true, logPath: tmpLog() });
  assert.equal(b.result, "entered");
  assert.ok(b.fields.includes("declined") && b.fields.includes("answer") && b.fields.includes("postcode"), b.fields.join());
});
