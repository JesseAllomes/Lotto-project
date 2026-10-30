# CAPTCHA skip audit — which skips are false positives, and a precise detection rule

Snapshot: `data/entries/log.jsonl` as at 2026-10-30 21:52 UTC (no `log_reenter.jsonl` exists). 40 competitions whose latest
result is `skipped` with reason `captcha` (38) or `human_check` (2). 16 of the 38 captcha skips came from the 14:25 dry run,
24 from live runs (14:42–14:54 and 21:06). Every page was loaded dry in headless Chromium (Playwright, no fill, no submit);
36 distinct pages were inspected (the five australianmade pages share one platform, one was loaded).

**Measured** = seen in this inspection. **Estimated** = inferred from the log and the platform's known behaviour (cannot be
measured without submitting, which this audit did not do).

## Why the current check misfires

`fillForm` skips when `CAPTCHA` matches *any frame URL* or `class="…g-recaptcha|h-captcha|cf-turnstile"` appears anywhere in
the HTML. Measured causes of the false positives:

1. **reCAPTCHA v3 / Enterprise / invisible v2 badge** (`api.js?render=<sitekey>`, `anchor?…size=invisible`, badge 256x60 in a
   corner): scores silently, no human interaction. 10 of the skips.
2. **`www.google.com/recaptcha/api2/aframe`**: a 0x0 frame opened by Google tags/ads on sites with no reCAPTCHA widget at all
   (beat.com.au x2, modmove, bountyparents). It is not a captcha.
3. **Widget on a different form** (newsletter sign-up with invisible v2, while the competition form has none): russh.
4. **Cloudflare interstitial inside a gleam.io embed** ("One more step — Please complete this security check to access
   gleam.io"): a site-level managed challenge shown to our headless browser; 5 skips. Not a form captcha; a human in a normal
   browser is normally waved through (estimated). Headless never cleared it in 30 s (measured).
5. **Shopify post-submit `/challenge`** (7 skips, all live with 1 field filled): no captcha before filling; after submitting a
   Shopify `/contact#…` newsletter/pop-up form, Shopify sent the browser to `/challenge`. In 6 of the 7 cases the form submitted
   was not the competition form (footer newsletter, "10% off" pop-up, contact form); the real entry was a ViralSweep widget,
   a spin-wheel app or a separate app form.
6. **`human_check`** (2): "Something went wrong / An error occurred … try again" on a second live attempt at a competition the
   log already marks `entered` at 14:51 the same day. A duplicate-entry rejection, not a bot check (estimated).
7. **Login wall, not captcha** (australianmade x5): the v2 checkbox exists but sits in a hidden register form; the page says
   "Members Only — Join the club or Login". Should be `login`/`no_form`.

Only 4 of the 40 are a genuine interactive challenge on the entry form (measured): Advil Spilt Milk (v2 checkbox), Sunday
(Turnstile managed checkbox), Modmove (custom "Security Code" image, which the current check caught only by luck via `aframe`),
and On Your Markus (Turnstile `interaction-only`, which stays hidden for ~10 s then renders a visible widget for our browser
and never issues a token; a human most likely sees nothing).

## Per-competition table

Verdicts: **FP** = false positive (no interactive challenge on the form; the entrant should fill and submit) · **TP** = interactive
challenge on the entry form (skip is right) · **BLOCK** = site-level challenge/interstitial against our browser, no form captcha
(stays manual, but should be labelled as a block, not a captcha) · **LOGIN** = login wall mislabelled as captcha ·
**POST** = no captcha before filling; Shopify challenged after submit (estimated).

| id | title | draw | vendor seen | mode / where | verdict | basis |
|---|---|---|---|---|---|---|
| 76056 | Harvey Norman Jillaroos RLWC pack | skill | reCAPTCHA Enterprise (recaptcha.net) | invisible badge, outside the Wufoo form | **FP** | measured; new fn: proceed |
| 76099 | Sheridan Restful Retreat | skill | none on reload | no vendor frame, widget or class | **FP** (original trigger not reproducible) | measured |
| 76125 | Advil Spilt Milk VIP tickets | skill | reCAPTCHA v2 | `anchor?size=normal`, 304x78 visible, inside entry form | **TP** | measured; new fn: skip |
| 76162 | Panasonic garment steamer | skill | reCAPTCHA Enterprise (recaptcha.net) | invisible badge; no form in view | **FP** (captcha); form still to be found | measured |
| 76163 | Panasonic 4K Blu-ray | skill | same as 76162 | same | **FP** | measured |
| 70434 | Clickability iPad/Tab | chance | Cloudflare Turnstile | interstitial inside gleam.io iframe, 300x65 "Verifying…", no clear in 30 s | **BLOCK** | measured |
| 72120 | Stan Cash spin-to-win | instant | reCAPTCHA v3 (`render=sitekey`) | badge bottom-left; no entry form found (wheel app) | **FP** → likely `no_form` | measured |
| 73803 | Bounty Parents $100k | chance | reCAPTCHA v3 | hidden badge; entry form is a Wayin/Engage iframe with no widget | **FP** | measured; new fn: proceed |
| 74216 | Dream Queen Coach Tabby | chance | none (page now 404) | earlier skip was post-submit on footer newsletter | **POST**, comp page gone | measured 404; estimated |
| 74311 | Ha-Ra $100 voucher | chance | none on page | post-submit skip after `/contact` form (1 field) | **POST** (wrong form) | estimated |
| 74560 | Choc D Full spin-to-win | chance | none on page | post-submit skip after footer newsletter | **POST** (wrong form) | estimated |
| 74891 | Pacific Fair Andaz getaway | chance | reCAPTCHA invisible v2 | `size=invisible` 0x0 inside the Jotform; bframe hidden | **FP** (Google may still challenge after submit; post-submit check handles) | measured; new fn: proceed |
| 75008 | Cove Magazine La-Z-Boy | chance | reCAPTCHA v3 (Gravity Forms `ginput_recaptchav3`) | badge only | **FP** | measured; new fn: proceed |
| 75359 | Society of Wolves $1K | chance | Turnstile api.js loaded, no widget | comp is a ViralSweep iframe; entrant submitted footer newsletter | **POST** (wrong form) | measured load; estimated submit |
| 75488 | Wintec saddle | chance | Cloudflare Turnstile | gleam.io interstitial | **BLOCK** | measured |
| 75543 | Australian Made – Grain Shop | unknown | reCAPTCHA v2 | `size=normal` but 0x0, in a hidden register form; page says Members Only | **LOGIN** | measured |
| 75544 | Australian Made – Provex | unknown | same platform | same | **LOGIN** | estimated (same template) |
| 75545 | Australian Made – Sarah Munnings | unknown | same platform | same | **LOGIN** | estimated |
| 75546 | Australian Made – Magic Soakers | unknown | same platform | same | **LOGIN** | estimated |
| 75548 | Australian Made – POP table | unknown | same platform | same | **LOGIN** | estimated |
| 75601 | LEGO Halloween bundle (account register) | chance | hCaptcha (Shopify storefront forms) | `data-size=invisible`, 0x0, "Protected by hCaptcha" badge | **FP** | measured; new fn: proceed |
| 75662 | TravelOnline Bali | chance | Cloudflare managed challenge | HTTP 403 "Just a moment…", whole page | **BLOCK** | measured |
| 75676 | Beat – Wild Horses passes | unknown | `recaptcha/api2/aframe` only | Google tag frame, 0x0; Campaign Monitor form has no widget | **FP** | measured |
| 75725 | Sunday Bali/Byron trip | chance | Cloudflare Turnstile managed | visible "Verify you are human" checkbox inside entry form; no token after 30 s | **TP** | measured; new fn: skip |
| 75739 | Tentworld fridge | chance | reCAPTCHA v3 | badge bottom-right; only footer newsletter email found | **FP** (captcha) → likely `no_form` | measured |
| 75893 | Robina Town Centre gift card | chance | Cloudflare managed challenge | HTTP 403 "Just a moment…" | **BLOCK** | measured |
| 75903 | RUSSH Olga Joan | chance | reCAPTCHA invisible v2 (Gravity Forms) | on a separate JOIN NOW form; comp form (Campaign Monitor) has none | **FP** | measured; new fn: proceed |
| 75967 | Beat – Polaroid | chance | `aframe` only | as 75676 | **FP** | measured |
| 75981 | Azadi $2,000 voucher | chance | Turnstile api.js loaded, no widget | post-submit skip after footer `/contact` form | **POST** (wrong form) | estimated |
| 76026 | Snotty Noses $10K baby pack | chance | none | Klaviyo form; "An error occurred when submitting. Please try again later." on a repeat attempt of a comp `entered` at 14:51 | **FP** (`human_check`; duplicate) | log; estimated |
| 76049 | Mr You Who Spark rings | chance | Cloudflare Turnstile | gleam.io interstitial | **BLOCK** | measured |
| 76050 | Suku Home bedding | chance | none | post-submit skip after "10% off" `/contact#ContactPopup` | **POST** (wrong form) | estimated |
| 76051 | Modmove – How to Rob a Bank | chance | custom image captcha (`captchaimg_1`, "Security Code") + `aframe` | visible, inside entry form | **TP** (right outcome, wrong trigger) | measured; new fn: skip |
| 76088 | Dahon e-bikes | chance | none | Shopify `/contact` "Enter your email to win" form; post-submit skip | **POST** (this one is the comp form) | measured load; estimated submit |
| 76110 | Popcorn Podcast Paw Patrol | chance | reCAPTCHA Enterprise (Squarespace) | invisible badge, outside form | **FP** | measured; new fn: proceed |
| 76111 | Annke cameras | chance | Cloudflare Turnstile | gleam.io interstitial | **BLOCK** | measured |
| 76112 | HipKids playroom | chance | Cloudflare Turnstile | gleam.io interstitial | **BLOCK** | measured |
| 76136 | Yarn bedroom pack | chance | none | "Something went wrong. Please try again." on a repeat attempt of a comp `entered` at 14:51 | **FP** (`human_check`; duplicate) | log; estimated |
| 76161 | On Your Markus Heartbreak Choir | chance | Cloudflare Turnstile `interaction-only` | hidden at load; visible 300x65 after ~10 s, no token in 30 s | **TP** for our browser (human likely sees nothing) | measured; new fn: skip |
| 76174 | Sportscraft $1K wardrobe | chance | hCaptcha (Shopify Forms embed, shadow DOM) | 0x0 `aria-hidden`; challenge frame parked at y=-9999 | **FP** | measured |

Totals (40): **FP 17** (15 captcha + 2 human_check), **TP 4**, **BLOCK 7**, **LOGIN 5**, **POST 7**. Of the 5 skill comps,
4 are false positives. The three `failing (form said: try again)` rows (76090, 76086, 76022 — all Shopify) showed no captcha
on load either; they are generic errors.

Side findings: the 21:06 live run re-attempted 76026 and 76136, which were already `entered` at 14:51 — the queue should not
re-submit a comp already entered unless it is a daily-entry comp. 74216's entry page is gone (404 → quiz page).

## Detection spec

Skip as `captcha` **before submitting** only when an interactive challenge is *in, or attached to, the chosen form* (`scope`,
the `<form>` holding the email box, or that frame's body), where "interactive" means a human would have to act:

| Condition (all checked against `scope`, through shadow DOM and one level of nested iframe) | Verdict |
|---|---|
| Visible (≥100x40, on-screen, not `visibility:hidden`/`display:none`/`opacity:0`) reCAPTCHA `api2|enterprise/anchor` iframe whose URL `size` is not `invisible` | skip: v2 checkbox |
| Visible reCAPTCHA `bframe` (the image challenge pop-up) | skip: challenge open |
| Visible hCaptcha checkbox iframe (`hcaptcha.com/…/hcaptcha.html`, not 0x0, not off-screen) | skip: hCaptcha checkbox |
| Visible Turnstile iframe (`challenges.cloudflare.com/cdn-cgi/challenge-platform/…`) **and** the form's `cf-turnstile-response` is still empty after `tokenWait` (12 s) | skip: Turnstile awaiting interaction |
| Visible captcha image / "security code" field (`img[alt*=captcha]`, `img[alt*='security code']`, `input[name*=captcha]`) | skip: security-code field |
| Anything else: `size=invisible` anchors, badges (`.grecaptcha-badge`), `render=<sitekey>` v3/Enterprise scripts, `data-size=invisible` hCaptcha, Turnstile `interaction-only` with a 0-height host, vendor frames outside the form, `api2/aframe`, vendor scripts merely loaded | **proceed**: fill and submit |

The Turnstile token wait is not a bypass: a managed widget verifies on its own for a human too; if it finishes by itself there
is no interaction, if it does not the comp is skipped exactly as before.

Timing: run the check **immediately before clicking submit** (and, in dry mode, before returning `dry_ok`), not at page load.
Measured: Sunday's Turnstile was 1x1 at 5 s and 300x65 at 15 s; On Your Markus's `interaction-only` widget appeared only after
~10 s. By submit time the fill loop has taken that long anyway. An early call with `{ tokenWait: 0 }` right after `scope` is
chosen is optional and only saves filling time on v2/hCaptcha/image captchas.

**After submit** (replacing `CAPTCHA.test(frames)` on line 293): skip as `captcha` only when the URL path has `/challenge`, the
title is "Just a moment…/Attention Required", or a vendor *challenge* frame (bframe, hCaptcha challenge, Turnstile) is now
visible. An anchor/badge frame alone is never a challenge. Keep the existing `human_check` text test, but (a) do not
re-submit a comp already `entered` (the two `human_check` rows were duplicates), and (b) consider moving "try again /
something went wrong" to `failed: form said …` and keeping `human_check` for explicit bot wording
(`blocked|suspicious|unusual|robot|automated|verify you are human`).

**No form found** (the `no_form` path): if a visible Cloudflare/hCaptcha challenge frame exists anywhere on the page, or the
title is "Just a moment…", or the page contains "complete this security check to access", log reason `blocked` (an
interstitial against our browser, e.g. gleam.io, TravelOnline, Robina) instead of `captcha`, so the manual list says what it is.

Remove: the page-load checks on lines 164–168 and 184 (`CAPTCHA.test(frames)` and the `class="…g-recaptcha|h-captcha|cf-turnstile"` regex).

## Drop-in function (Playwright)

Tested offline against the fixtures below (11/11 pass) and dry against live pages: skip on 76125, 75725, 76051, 76161;
proceed on 73803, 74891, 75008, 75601, 75903, 76056, 76088, 76110. The `root`/`scope` arguments are the ones `fillForm`
already has at line 192.

```js
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
async function interactiveChallenge(page, root, scope, opts = {}) {
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
async function challengeAfterSubmit(page) {
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
```

Wiring in `fillForm`:

```js
// line 164-168 and 184: delete the CAPTCHA.test(frames) / class="…" checks.
// after line 192 (scope chosen), optional fast fail:
//   const early = await interactiveChallenge(page, root, scope, { tokenWait: 0 });
//   if (early && !/Turnstile/.test(early)) return { result: "skipped", reason: "captcha", fields: [], said: early };
// before `if (!live)` (line 268) and therefore before the submit click:
//   const why = await interactiveChallenge(page, root, scope);
//   if (why) return { result: "skipped", reason: "captcha", fields: [...filled], said: why };
// line 293: replace `CAPTCHA.test(page.frames()...) || /\/challenge\b/...` with `await challengeAfterSubmit(page)`.
```

## Test fixtures

Serve each as the page (vendor iframe URLs stubbed with `context.route("**/*", …)`), pick `scope` as `fillForm` does, call
`interactiveChallenge(page, page.mainFrame(), scope, { tokenWait: 1500 })`. Shared form shell:

```html
<form id="comp" action="/enter"><h2>Win a prize</h2>
  <input name="first" placeholder="First name"><input type="email" name="email" placeholder="Email">
  <!-- fixture-specific markup goes here -->
  <button>Enter now</button></form>
```

**1. Visible reCAPTCHA v2 checkbox in the form → skip** (`captcha: reCAPTCHA v2 checkbox`)
```html
<div class="g-recaptcha" data-sitekey="6LTEST"><div style="width:304px;height:78px">
  <iframe title="reCAPTCHA" src="https://www.google.com/recaptcha/api2/anchor?ar=1&k=6LTEST&co=aHR0&hl=en&size=normal" width="304" height="78"></iframe></div></div>
<textarea name="g-recaptcha-response" style="display:none"></textarea>
```

**2. Invisible v2 / v3 badge → proceed** (hidden response field in the form, badge in the page corner, outside the form)
```html
<script src="https://www.google.com/recaptcha/api.js?render=6LTEST"></script>
<!-- inside the form: --> <input type="hidden" name="g-recaptcha-response">
<!-- after the form: -->
<div class="grecaptcha-badge" style="position:fixed;bottom:14px;right:-186px;width:256px;height:60px">
  <iframe title="reCAPTCHA" src="https://www.google.com/recaptcha/api2/anchor?ar=1&k=6LTEST&co=aHR0&hl=en&size=invisible" width="256" height="60"></iframe></div>
```

**3. Turnstile managed, visible, no token → skip** (`captcha: Turnstile awaiting interaction`); the same markup with
`value="0.ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"` in the response input → proceed; with `data-appearance="interaction-only"`
and a 0-height host/iframe → proceed.
```html
<div class="cf-turnstile" data-sitekey="0x4TEST" style="width:300px;height:65px">
  <iframe title="Widget containing a Cloudflare security challenge" src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/f/av0/rch/abc/0x4TEST" width="300" height="65"></iframe></div>
<input type="hidden" name="cf-turnstile-response" value="">
```

**4. Captcha script and a visible v2 widget on the page, but on another form → proceed**
```html
<script src="https://www.google.com/recaptcha/api.js?render=explicit"></script>
<!-- competition form: the shell above with nothing extra -->
<footer><form action="/newsletter"><input type="email" name="EMAIL">
  <div class="g-recaptcha"><iframe title="reCAPTCHA" src="https://www.google.com/recaptcha/api2/anchor?ar=1&k=6LTEST&co=aHR0&hl=en&size=normal" width="304" height="78"></iframe></div></form></footer>
```

**5. Custom "security code" image in the form → skip** (`captcha: security-code field`; the Modmove case)
```html
<label>Security Code:</label><img id="captchaimg_1" alt="security code" src="/captcha.png" width="120" height="40"><input name="cp_captcha">
```

**6. Shopify-style invisible hCaptcha in the form → proceed**; the same with a visible 303x78 checkbox iframe → skip
(`captcha: hCaptcha checkbox`).
```html
<div class="h-captcha" data-size="invisible" data-sitekey="x" style="height:0"><iframe src="https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=checkbox" width="0" height="0" aria-hidden="true"></iframe></div>
<textarea name="h-captcha-response" style="display:none"></textarea>
<!-- after the form: --> <div style="position:absolute;top:-9999px"><iframe title="hCaptcha challenge" src="https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=challenge" width="300" height="150"></iframe></div>
```

**Post-submit**: a page with only an `anchor?…size=invisible` iframe → `challengeAfterSubmit` returns null; a page with a visible
400x580 `recaptcha/api2/bframe` iframe → `captcha: challenge opened after submit`.

## Limits of this audit

- Headless Chromium from a cloud IP; vendors may treat the production entrant differently. Nothing was submitted, so the
  Shopify `/challenge` and duplicate-rejection explanations are inferred from the log (`fields` length, earlier `entered` rows)
  and platform behaviour, not observed.
- The log was being appended by a live run during the audit; the table reflects 21:52 UTC.
- The entry forms for 72120, 75739, 76162 and 76163 were not located within 6 s of load, so those comps may end as `no_form`
  after the rule change rather than being entered.
