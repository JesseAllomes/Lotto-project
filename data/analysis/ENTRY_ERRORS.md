# Entry errors audit — live run 41141359948 (log rows after 2026-10-30T22:56Z)

Every page below was loaded **dry** in headless Chromium (Playwright 1.63, fake details, no submit click, any
form-looking POST aborted at the network layer). Evidence is from the DOM, frames, load-time network, the vendors'
own JavaScript and harmless GET/OPTIONS header probes. Nothing was entered; no bot check was solved or evaded.

**Measured** = seen in this inspection. **Estimated** = inferred; it cannot be measured without submitting.

Note on the code: commit `56f9673` (23:28Z, after the run) already maps "Captcha validation failed" to
`skipped/captcha` and "An error occurred when submitting" on `/pages/` URLs to `skipped/human_check`. The run used
the older code, which is why those rows say `failed`. The fixes below build on the current file.

## Per-competition table

| id | site / platform | symptom (log) | root cause, with evidence | verdict |
|---|---|---|---|---|
| 75784 | lifecykel.com (Shopify) — **Klaviyo embedded form** | `failed` "An error occurred when submitting. Please try again later." x2 | The competition form is `form.klaviyo-form` (first name, email, `phone-number` + "Search Countries" dial picker). It is **not** the `/contact` form and not Shopify Forms. The dial picker is already Australia; `0400000000` passes Klaviyo's client-side check (measured, no `aria-invalid`, no error text). Klaviyo's form bundle (`Render.d9de14477b3e9.js`) posts to `https://a.klaviyo.com/client/profiles/`, logs `"Submit Action \| Datadome Bot Detection Triggered"`, sets `window.DataDomeCaptchaDisplayed`, keeps `onsiteState.datadomeCaptchaUrls[form]`, and throws a generic error on any non-202 (403 → bot error class). `OPTIONS/GET a.klaviyo.com/client/subscriptions/` answers `x-datadome: protected` + `Set-Cookie: datadome=…` from this network (measured). The message is Klaviyo's default submit-error text (identical on all four sites). | **site refuses automation** (Klaviyo + DataDome, headless + datacenter IP) |
| 75677 | infamousswim.com.au (Shopify) — Klaviyo embedded form | same, x2 | Same form class and fields (`first_name_…`, `email`, `phone-number`, "Search Countries"). Same backend. | site refuses automation |
| 75328 | calexico.com.au (Shopify) — Klaviyo embedded form | same, x2 | Same, plus a Klaviyo `Birthday_…` text box (we fill `02/01/1980`; Klaviyo's birthday box takes free text, estimated fine). | site refuses automation |
| 76026 | snottynoses.com.au (Shopify) — Klaviyo embedded form | `entered` once (22:5x), then "An error occurred…" x3 | Same form. One pass then refusals = per-request DataDome scoring, not a duplicate check (the three other sites were refused on their first try). The earlier audit's "duplicate-entry rejection (estimated)" for `human_check` rows is superseded by this. | site refuses automation |
| 76136 | yarn.com.au (Shopify) — theme form `yf-fstep` | `failed` "Something went wrong. Please try again." x2 | Custom theme script `yarn-first.js`: `fetch("https://a.klaviyo.com/client/"+path…)` (`subscriptions`), converts the mobile to E.164 itself (`toE164`), and shows `err.network` = "Something went wrong. Please try again." on any `!r.ok`. Same DataDome-fronted Klaviyo endpoint as above (measured `x-datadome: protected` on `/client/subscriptions/`). Fields we filled were right (email, phone, required consent). | site refuses automation |
| 75764 | venturehunting.com.au (Shopify) | `no_form` | `GET /pages/vivobarefoot-forest-boots-giveaway` → **301** → `/collections/vivobarefoot` (measured). The giveaway page has been removed; the collection page has no email box. | **page has no entry form** (gone) |
| 75543 75544 75545 75546 75548 | australianmade.com.au `/competitions/…` (Umbraco) | `no_form` | Competitions are for **Australian Made Club** members: the page has only hidden login/registration modals (`loginModel.Username/Password`, `registrationModel.*` with a **reCAPTCHA v2 checkbox**), no entry form for visitors (measured). Needs an account the entrant must not create. | **needs the owner** (club login); should log as `login`, not `no_form` |
| 75926 | stjohnvic.com.au/shocktober-1/ (Umbraco Forms) | `no_form` | The form exists but every box has a GUID `name`/`id` and only a `<label for>` ("Email *"), so the `EMAIL` selector misses it (measured). Even when found: `Organisation *`, `Your Role *`, where the AED will be placed, a **required file upload** and a honeypot text box. It is a workplace/community AED application, not a personal entry. | **needs the owner** (and `no_form` is the wrong reason — fix below gives `unfillable: Organisation`) |
| 75557 | whitefoxboutique.com.au (Shopify) | `no_form` | The listing's `entry_url` is the **terms** page. Clause 5 of that page says "To enter the Promotion, visit: https://whitefoxboutique.com.au/pages/hermes-birkin-25-giveaway". That page (loaded dry) has a real theme form: first/last/email, **Gender\*** select (has "Prefer not to say"), phone with +61 picker, birthday, country, post code, a **required answer textarea** ("five essentials you'd put inside"), terms box. Current code on it: `unfillable: select gender`. | **needs the owner** (skill answer) after **our bug** (follow the terms link, pick "Prefer not to say") |
| 76107 | agvhelmets.com.au/win/ (WordPress) — **SweepWidget** iframe | `failed` "no confirmation seen", fields `["email"]` x2 | The entry is SweepWidget's login step inside `sweepwidget.com/c/102752-…-embedded`: "Full Name \*" box `id=sw__login_name placeholder="John Doe"` (not `required`, no `<label>`) and an email box. `classify("sw__login_name John Doe")` → `null` (`\bname\b` fails on `login_name`), so the name was left blank and "Enter Giveaway" was clicked; SweepWidget's own validation holds the step (measured desc/classify; the refusal is estimated). The frame also needs >8 s to render (measured: 12 s poll needed; the single 5 s wait misses it, hence my dry `no_form`). Caveat: SweepWidget loads IPQualityScore device fingerprinting (`ipqsnet.com`, `df.sw-….com`); it may still reject headless after the fix (estimated). | **our bug** (name classification + late embed) |
| 74311 | hara.com.au blog (Shopify) | `failed` "no confirmation seen", fields `["email"]` x2 | The post explains a monthly draw for **product reviews**; the only email box on the page is the footer newsletter `/contact#contact_form` (`contact[tags]=prospect,newsletter`). `findEmail` returned it with score −2 (footer, no comp words) and the entrant submitted a newsletter sign-up as the "entry". | **page has no entry form** (and **our bug**: negative-score forms must not be submitted) |
| 75889 | app.viralsweep.com (ViralSweep) | `blocked` | Page title "Just a moment…", `cdn-cgi/challenge-platform` + Turnstile: Cloudflare managed challenge on the whole sweep page (measured). | site refuses automation |
| 70434 | clickability.com.au — **gleam.io** embed | `blocked` (live) / `no_form` (dry today) | The gleam.io embed frame shows "Performing security verification … Cloudflare" with Turnstile (measured). `interstitial()` only checks the main frame's text and Cloudflare-URL frames with visible geometry, so the embed's own challenge page is sometimes read as "no form". | site refuses automation (should always log `blocked`) |
| 76110 | popcornpodcast.com (Squarespace form) | `failed` "Captcha validation failed. Please try again." x2 | Squarespace `react-form-contents` with **reCAPTCHA Enterprise invisible** (`recaptcha/enterprise/anchor`, measured). Squarespace's server scored the invisible token as bot. Current code already maps this line to `skipped/captcha`. | site refuses automation |

**Counts (18 comps):** site refuses automation 8 (5 Klaviyo/DataDome, 2 Cloudflare interstitials, 1 reCAPTCHA
Enterprise) · needs the owner 7 (5 Australian Made Club, St John, White Fox answer) · page has no entry form 2
(venturehunting gone, hara review-based) · our bug 1 primary (agvhelmets) plus classification bugs on hara,
whitefox, stjohn and the `no_form` family.

Telling "the site refused us" from "our bug": for every "refused" row the fields we filled were the right ones
and valid client-side; the refusal came from a vendor endpoint that is bot-protected (DataDome, Cloudflare, reCAPTCHA
Enterprise). For the two "our bug" rows the page shows exactly what we missed (a name box; a review-based comp with
no form).

## Fixes (verified on a scratch copy: 15 existing + 8 new tests pass)

All in `workers/entrant.mjs`. Scratch copy with the patch applied, fixtures and tests:
`/tmp/claude-0/-home-user/bf71d36f-697a-54ce-b63a-de8fb21301e9/scratchpad/ent/` (`patch.py` holds the exact
old→new strings; `tests/new.test.mjs`, `tests/fixtures/forms/new/`).

### F1. `classify`: underscores/hyphens/brackets are word breaks; "John Doe" placeholders are a full-name box (agvhelmets)

```js
// old
  const d = desc.toLowerCase();
  if (type === "password") return "password";
// new
  const d = desc.toLowerCase().replace(/[_\-.[\]]+/g, " ");      // sw__login_name, contact[first-name] -> words
  if (type === "password") return "password";

// old
  if (/full ?name|your name|^name$|\bname\b/.test(d)) return "full";
// new
  if (/full ?name|your name|^name$|\bname\b|john doe|jane doe/.test(d)) return "full";
```

Fixture `tests/fixtures/forms/sweepwidget.html` (no `<form>`, as SweepWidget renders it):

```html
<html><body><div id="sw"><h2>AGV + Motul Giveaway</h2><p>It's easy to enter</p>
<div>Full Name *</div><input type="text" id="sw__login_name" placeholder="John Doe">
<div>Email Address *</div><input type="email" id="sw__login_email" placeholder="name@example.com">
<button id="sw_login" type="submit" onclick="login()">Enter Giveaway</button><p id="m"></p></div>
<script>function login(){var n=document.getElementById('sw__login_name').value;
if(!n){document.getElementById('m').innerText='Please enter your full name';return;}
document.getElementById('sw').innerHTML='<p>1 My Entries</p><p>Subscribe to the AGV Newsletter +1</p>';}</script></body></html>
```

Expected (live): `["entered", "form cleared"]`, fields include `full` and `email`. Before the fix: `failed`,
"form said: please enter". Unit: `classify("sw__login_name John Doe","text") === "full"`,
`classify("contact[first-name]","text") === "first"`, `classify("store_location Favourite store location","text") === null`.

### F2. `findEmail`: never submit a form that reads like a newsletter/pop-up (hara; also the earlier Shopify `/challenge` family)

```js
// old
  return best;
// new
  return best && best.score >= 0 ? best : null;   // only a footer sign-up or a discount pop-up: not the entry form
```

Fixture `footer_only.html`:

```html
<html><body><article><h1>Rate your favourite products every month and win a $100 voucher</h1><p>Leave a review on any product page to go in the draw.</p></article>
<footer><form action="/contact#contact_form"><input type="email" name="contact[email]" placeholder="Email" required><button type="submit">SUBSCRIBE</button></form></footer></body></html>
```

Expected: `["skipped", "no_form"]` (before: the footer form was submitted). `popup_and_comp.html` still picks the
competition form (its score is positive).

### F3. Late-loading embeds: poll up to 15 s instead of one 5 s wait (agvhelmets' SweepWidget needs ~10 s)

```js
// old
  if (!found) {                                   // late-loading forms
    await page.waitForTimeout(5000);
    found = await findEmail(page);
  }
// new
  for (const deadline = Date.now() + 15000; !found && Date.now() < deadline;) {   // late-loading forms and embeds (SweepWidget)
    await page.waitForTimeout(1500);
    found = await findEmail(page);
  }
```

Fixture `late_embed.html` (form injected after 9 s):

```html
<html><body><h1>Win a prize</h1><div id="slot"></div>
<script>setTimeout(function(){document.getElementById('slot').innerHTML='<form action="/enter"><input type="email" name="email"><input name="first_name"><button>Enter now</button></form>';},9000);</script></body></html>
```

Expected (dry): `["dry_ok", 'would click "Enter now"']` (before: `no_form`).

### F4. `findEmail`: boxes identified only by a `<label for>` "Email" (Umbraco Forms, stjohn)

```js
// old
      const boxes = f.locator(EMAIL);
// new
      const boxes = f.locator(EMAIL).or(f.getByLabel(/\be-?mail\b/i).and(f.locator("input:visible")));   // GUID-named boxes with an "Email" label
```

Fixture `umbraco.html`:

```html
<html><body><form action="/shocktober-1/" method="post"><h2>Shocktober Entries 2026</h2>
<label for="a1">First Name *</label><input type="text" id="a1" name="a1" aria-required="true">
<label for="a2">Email *</label><input type="text" id="a2" name="a2" aria-required="true">
<label for="a3">Organisation *</label><input type="text" id="a3" name="a3" aria-required="true">
<label for="a4">Upload your submission here *</label><input type="file" id="a4" name="a4">
<button type="submit">Submit</button></form></body></html>
```

Expected: `["skipped", "unfillable"]`, `fields[0]` matches `/Organisation/` (before: `no_form`, which the queue
retries on the closing day; `unfillable` goes straight to the manual list with the real reason).

### F5. Split `no_form` into `moved` / `login` / `blocked` (venturehunting, australianmade, clickability) and follow a terms page to its entry page (whitefox)

```js
// old
  if (!found) return { result: "skipped", reason: (await interstitial(page)) ? "blocked" : "no_form", fields: [] };
// new
  if (!found) {                                   // a terms page that says where the entry form is
    const next = await entryPageFromTerms(page);
    if (next) {
      await page.goto(next, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(2500);
      await dismissOverlays(page);
      found = await findEmail(page);
    }
  }
  if (!found) {
    if (await interstitial(page)) return { result: "skipped", reason: "blocked", fields: [] };
    const here = new URL(page.url()), from = new URL(item.entry_url);
    const trim = (u) => [u.hostname.replace(/^www\./, ""), u.pathname.replace(/\/+$/, "")];
    if (trim(here)[0] === trim(from)[0] && trim(here)[1] !== trim(from)[1]) return { result: "skipped", reason: "moved", fields: [] };   // the site redirected the entry page away
    if (await page.locator("input[type=password]").count()) return { result: "skipped", reason: "login", fields: [] };   // members-only page with a (hidden) login/register modal
    return { result: "skipped", reason: "no_form", fields: [] };
  }
```

New helper (place above `fillPickers`):

```js
// A terms page that names the entry page ("To enter the Promotion, visit: https://host/pages/x"): that page, once, on the same site.
async function entryPageFromTerms(page) {
  const text = await page.locator("body").innerText().catch(() => "");
  const m = text.match(/(?:to enter|how to enter|entry form|enter (?:the|this) (?:promotion|competition|giveaway))[^]{0,200}?(https?:\/\/[^\s)",']+|file:\/\/[^\s)",']+)/i);
  if (!m) return null;
  try {
    const u = new URL(m[1]), here = new URL(page.url());
    return u.host === here.host && u.pathname !== here.pathname ? u.href : null;
  } catch { return null; }
}
```

`interstitial()`: also read the text of every frame (gleam.io / ViralSweep embeds showing Cloudflare's page):

```js
// old
  if (/complete this security check to access/i.test(await page.locator("body").innerText().catch(() => ""))) return true;
  for (const f of page.frames()) {
    if (!/challenges\.cloudflare\.com\/|hcaptcha\.com\/.*hcaptcha\.html/i.test(f.url())) continue;
// new
  for (const f of page.frames()) {                                        // the page, or an embed (gleam.io, ViralSweep), is a Cloudflare page
    if (/just a moment|performing security verification|verify you are human|complete this security check/i.test(await f.locator("body").innerText().catch(() => ""))) return true;
  }
  for (const f of page.frames()) {
    if (!/challenges\.cloudflare\.com\/|hcaptcha\.com\/.*hcaptcha\.html/i.test(f.url())) continue;
```

Fixtures: `moved_from.html` = `<html><head><meta http-equiv="refresh" content="0;url=moved_to.html"></head><body></body></html>`,
`moved_to.html` = `<html><body><h1>Vivobarefoot Shoes</h1><p>Shop the collection.</p></body></html>`;
`login_wall.html`:

```html
<html><body><nav><a href="javascript:void(0)">LOGIN</a><a href="javascript:void(0)">JOIN CLUB</a></nav><h1>Win a heat bag</h1><p>Club members can enter.</p>
<div id="login-modal" style="display:none"><form><input name="Username"><input type="password" name="Password"><button>Login</button></form></div></body></html>
```

`gleam_blocked.html`:

```html
<html><body><h1>NDIS services giveaway</h1>
<iframe srcdoc="<html><body><p>Performing security verification</p><p>This website uses a security service to protect against malicious bots.</p></body></html>" width="600" height="400"></iframe></body></html>
```

Expected: `[["skipped","moved"], ["skipped","login"], ["skipped","blocked"]]` (before: all three `no_form`).

Terms test (the terms page is written at test time so it can hold the fixture's absolute `file://` URL):
`<p>5) How to Enter. … To enter the Promotion, visit: file:///…/wf_entry.html (Australian residents) …</p>` and
`wf_entry.html`:

```html
<html><body><form id="giveaway"><h2>Birkin 25 Giveaway</h2>
<input name="firstName" placeholder="First Name*" required><input name="lastName" placeholder="Last Name*" required><input type="email" name="email" placeholder="Email*" required>
<select name="gender" required><option value="">Gender</option><option>Female</option><option>Male</option><option>Other</option><option>Prefer not to say</option></select>
<input type="tel" name="phone" required><input name="zip_code" placeholder="Post code" required>
<textarea name="submission" placeholder="Your answer" required></textarea>
<label><input type="checkbox" name="terms" required> I agree to the terms</label>
<button type="submit" onclick="event.preventDefault();document.body.innerHTML='<p>Thank you, you are in the draw</p>'">ENTER NOW</button></form></body></html>
```

Expected: from the terms page → `["skipped","needs_answer"]`; with `answer` set → `entered`, fields include
`declined`, `answer`, `postcode`. (Before: `no_form` on the terms page; `unfillable: select gender` on the entry page.)

### F6. A required select with "Prefer not to say" is answered that way (whitefox Gender)

```js
// old (select branch)
      if (info.required) return { result: "skipped", reason: "unfillable", fields: [`select: ${info.desc.slice(0, 60)}`] };
      continue;
// new
      const decline = info.options.find((o) => /prefer not to say|rather not say|not specified|unspecified/i.test(o.split("|")[0]));
      if (decline) { await el.selectOption({ value: decline.split("|")[1] }); filled.add("declined"); continue; }
      if (info.required) return { result: "skipped", reason: "unfillable", fields: [`select: ${info.desc.slice(0, 60)}`] };
      continue;
```

Covered by the terms test above.

### F7. Klaviyo forms: recognise the vendor and send its generic error straight to the manual list (replaces the `/pages/` heuristic)

```js
// old
  const filled = new Set();
  const hasCC = await scope.locator("select:visible")
// new
  const filled = new Set();
  // Klaviyo embedded forms post to a.klaviyo.com, which DataDome fronts (data/analysis/ENTRY_ERRORS.md): a refusal there
  // comes back as the form's generic error line, so any such reply goes to the manual list, not a retry.
  const klaviyo = await scope.evaluate((e) => !!(e.closest("form.klaviyo-form") || e.querySelector("form.klaviyo-form, input[name='phone-number'][type='tel']"))).catch(() => false);
  const hasCC = await scope.locator("select:visible")

// old
    if (/blocked|suspicious|unusual|robot|automated|verify you are human/i.test(said) ||
        (/\/pages\//.test(item.entry_url) && /an error occurred when submitting/i.test(said))) {
      return { result: "skipped", reason: "human_check", fields: [...filled], said };   // anti-bot rejection (Shopify's)
    }
// new
    const fieldError = /required|invalid|not valid|please (enter|provide|select|check|complete|fill)/i.test(said);
    if (/blocked|suspicious|unusual|robot|automated|verify you are human/i.test(said) ||
        (!fieldError && (klaviyo || /an error occurred when submitting/i.test(said)))) {
      return { result: "skipped", reason: "human_check", fields: [...filled], said: klaviyo ? `klaviyo: ${said}` : said };   // a bot check said no (Klaviyo/DataDome, Shopify)
    }
```

Fixture `klaviyo_error.html`:

```html
<html><body><form class="needsclick klaviyo-form klaviyo-form-ABC" data-testid="klaviyo-form-ABC" onsubmit="event.preventDefault();document.getElementById('m').innerText='An error occurred when submitting. Please try again later.'">
<h2>WIN THE ULTIMATE RESET</h2><input type="text" name="first_name_01ABC" placeholder="First name"><input type="email" name="email" placeholder="Email">
<button type="button" aria-label="Search Countries" role="combobox" aria-haspopup="listbox">+61</button><input type="tel" name="phone-number" placeholder="Mobile">
<button type="submit">ENTER NOW →</button><p id="m"></p></form></body></html>
```

Expected: `["skipped","human_check"]`, `said` starts `klaviyo: An error occurred when submitting`. `rejected.html`
("Something went wrong, please try again later." on a plain form) stays `failed` — a generic error on an unknown
backend still gets its one retry, and two failures already put a listing on the manual list.

Why not skip Klaviyo forms before submitting: snottynoses passed once (DataDome scores per request), one attempt is
cheap, and a refusal now lands on the manual list immediately with the vendor named. Do **not** try to get past it
(no stealth, UA or proxy tricks): the owner enters those five by hand.

## Classification changes (`workers/entry_queue.py` and the manual list)

- Add `"moved"` and keep `"login"`, `"blocked"`, `"human_check"` in `BLOCKING`; none of them should be in
  `RETRY_ON_LAST_DAY`. `no_form` can stay retried on the closing day now that the gone/login/blocked cases no
  longer hide inside it.
- Straight to the manual list, no second attempt: any `human_check` (now including every Klaviyo form error and
  yarn-style Klaviyo API forms once they fail once), `captcha` replies ("Captcha validation failed"), and `blocked`.
  For yarn specifically the current two-failure rule already does this.
- For this run: put 75784, 75677, 75328, 76026, 76136 (Klaviyo), 76110 (Squarespace reCAPTCHA Enterprise), 75889
  and 70434 (Cloudflare) on the manual list as "site's bot check"; 75543–75548 as "Australian Made Club login";
  75926 as "organisation/AED application"; 75557 as "needs the 5-essentials answer; entry page is
  /pages/hermes-birkin-25-giveaway, not the terms page" (and point `entry_url` there in the listing); 75764 as
  "entry page removed"; 74311 as "review-based draw, no form"; retry 76107 after F1+F3.
- `data/analysis/CAPTCHA_CHECK.md` item 6 ("human_check = duplicate-entry rejection, estimated") is superseded:
  those lines are Klaviyo/DataDome refusals.
