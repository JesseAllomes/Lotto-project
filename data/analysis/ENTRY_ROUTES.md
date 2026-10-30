# Entry routes for comps the entrant cannot enter

Written 2026-10-30 from `data/entries/manual.csv` (245 open comps), `data/comps/odds.csv`,
`data/comps/comps.jsonl`, `data/entries/log.jsonl`, 26 page fetches and 4 web searches.
Labels: **measured** (from our data), **sourced** (from a fetched page, quoted), **estimated** (my judgement).
Rule kept throughout: no CAPTCHA, bot-check or rate-limit evasion, no direct posting to form back ends,
no extra identities. Everything below is a route the promoter itself offers or the owner doing it by hand.

## 0. What the 245 manual comps actually are (measured)

| Bucket | n | Prize pool |
|---|---|---|
| `entry route manual` (classifier said not a plain form) | 138 | — |
| blocked: captcha | 33 | $192k |
| blocked: no_form / unfillable / login | 31 | — |
| blocked: form said error / try again / no confirmation | 25 | $36k |
| `entry route unknown` | 18 | — |
| Total | 245 | $2.95m (202 with a value) |

Only 20 of the 245 are on Facebook/Instagram; 225 are web pages. 83 of the 225 are Shopify stores (`/pages/`).

**The biggest single finding is a classifier false positive, not a missing route.** `workers/comp_odds.py`
line 165 routes a comp to `manual` when its description matches `phone`, so "participants must provide
their first name, email address, **phone number**" is treated like "enter by phone". Re-running the regex
over the 118 web comps marked `entry route manual` with "phone number / contact details / notified by phone"
masked out: **26 comps, combined prize pool $904,167, are plain web forms** (measured). They include
SmartMoney $500k, Home Beautiful / ELLE / Homes to Love $100k each, The Block $40k, Coopers $9.6k,
Tourism NT $9.9k, Volcom $3k. A further 8 comps ($52k) hit only `follow` where the follow is a *bonus*
entry on top of a form (AGV, ALYN Ring, My Touring, Natio, Equities Club). Fix: narrow the token to
`phone (?:entry|entries|line)|by phone|call ` and treat "additional/bonus entries ... follow" as agent_ok
for the base entry. Nothing else changes; each comp still goes through the automation-ban check.

## 1. Do promoters offer alternative entry methods? (sample of top 20 by value)

Fetched the entry/terms pages of the 20 highest-value manual comps. 12 were readable; 8 were walled
(Bunnings, Robina, Red Bull, Tradablebits/Carlton, Visa, 7plus, Nine/The Block, Flybuys 502).

Measured across all 245 descriptions: only 4 comps describe a non-web route that a Victorian at home can
use (Weekend Notes: entry *is* an email; Builders Discount Warehouse: in-store form, QLD; Visit Victoria
and Telfast: QR code *or* website). 17 mention SMS and 16 mention post, but every one is about winner
notification or a PO Box in the promoter's address, not entry. **No comp in the list offers postal entry.**

Sourced, from the sample:

- **SmartMoney $500k** (https://offers.smartmoneygroup.com.au/win500k, T&Cs PDF cl.6): "Register via
  smartmoneygroup.com.au or via Facebook lead form ... then ... a. complete a survey b. attend a
  webinar/seminar c. request a discovery meeting ... f. SMS opt in". Alternative routes exist but all are
  lead-generation steps. Cl.22: "Any entrant found to have used a third party to enter on their behalf will
  have all entries invalidated." Cl.10: one entry per person. Owner should enter this one by hand, once.
- **Modern Group $120k** (winwin.com.au, cl.12): enter via "Facebook, Instagram, TikTok, QR code (direct
  mail), and EDM/SMS" as well as the form. Cl.20: "The use of any automated entry software or any other
  mechanical or electronic means ... that allows an Eligible Entrant to automatically enter repeatedly is
  prohibited." One manual entry via the web form; the social routes add nothing.
- **Are Media $100k** (Marie Claire, ELLE, Home Beautiful, Homes to Love, Bounty Parents): the page offers
  "Having trouble entering online?" → https://ngx.me/737LK00 → a Wayin-hosted form with the same fields.
  Its terms: "Limit 1 entry/person/website/day. Aus. res. 18+ only. Starts 13/7/26. Ends 11:59pm AEDT
  1/11/26." That is five legitimate entries per day until Sunday, through the promoter's own alternate link
  (if it shows a CAPTCHA, the owner taps it; the entrant stops). Full rules:
  https://www.aremedia.com.au/wp-content/uploads/2026/07/ARE-Media-Chance-to-Play-to-Win-100000-2026.docx
- **RAC Arena $32k**: venue QR *or* the same online form. **MXstore $35k**: "online entry form ... No
  purchase is necessary." **Colorbond $35k**: photo + form, "enter as many times as you like."
  **Muscle Republic $31.5k**: form only. **ING $55k**: must "hold an active and unrestricted Orange Everyday
  account"; not enterable. **Flickerfest $150k**: make a film. **Koala $105k**: closed 29/10.
  **MTB Direct $22k**: "DM entries are ineligible"; entry is a public social post or product review.

Share of the readable sample with a usable second route: 3 of 12 ≈ 25% (measured, small sample); across
the whole list, a non-web route usable from home exists for 4/245 ≈ 2% (measured). Alternative routes will
not move the needle; the classifier fix and hand entry of the top 10 will.

## 2. Login-gated comps (Mouths of Mums and similar)

Measured: 16 MoM comps in `comps.jsonl`, 3 in the manual list ($274–$949). Sourced
(https://mouthsofmums.com.au/help-page/): competitions "fall under" the site's general terms; "mostly our
competitions require you to enter a 25 words or less creative answer ... other competitions you simply
need to click to enter"; recent ones are "open only to members"; MoM Rewards points accrue "while logged
in" for reviews, comments and entries. The terms page itself returned 403 to our fetcher, so **whether
scripted use of a member account is allowed is unverified**. A one-time free membership in the owner's own
name is plainly allowed (estimated, it is the designed path). A logged-in entrant is only worth building if
(a) the owner reads https://mouthsofmums.com.au/terms-and-conditions/ and finds no clause on automated
access, and (b) it is limited to "click to enter" comps; the 25-word ones need the owner anyway. Expected
gain is small: 16 comps, low value. Same logic for Esmi, 7plus, Disney+ Perks, Visa and Flybuys/Velocity
($261k, page 502'd): the owner creates the account once; the entrant runs logged-in only where the site's
terms are silent on automation. Flybuys/Velocity are free programs the owner may already hold (estimated:
highest value of the login group, 5-minute signup, then one manual entry).

## 3. Shopify-store giveaways (83 of 225 web comps, measured)

Entrant log for Shopify URLs: 53 "no confirmation seen", 22 "form said: error", 19 click timeouts, 10
CAPTCHA, 6 "try again" (measured). These are Klaviyo/Shopify forms with bot protection; we do not go round
it. Pattern (sourced from descriptions and fetched pages): where a second route exists it is almost always
the brand's own Instagram post (follow + comment/tag), e.g. ALYN Ring: "complete the entry form ... For
bonus entries, follow @alynring"; Lapoche: Instagram only. Email or DM entry is rare and sometimes excluded
(MTB Direct: "DM entries are ineligible"). Salty Johnson alone states an equivalent route: "through the form
on saltyjohnson.com.au or via a Salty Johnson popup or social media sign-up form". Conclusion: the
legitimate second route for Shopify comps is the owner tapping through the form or the Instagram post,
~45 seconds each with browser autofill. 25 comps / $228k sit in the captcha + "form said error" buckets.

## 4. Ranked ideas, by entries gained per owner-minute (estimated unless marked)

1. **Fix the `phone` / bonus-`follow` false positives** in `comp_odds.py` (10 min once): +26 to +34 comps,
   $950k pool, zero owner minutes per entry afterwards (measured count, estimated effort).
2. **Are Media daily tap-through** via the promoter's alternate link: 5 entries/day × 2 remaining days, ~30 s
   each, $100k prize (sourced limit).
3. **Hand-enter the top 10 by value** from the tap-through page (SmartMoney, Modern Group, MXstore, RAC
   Arena, Colorbond, Muscle Republic, MTB Direct, Koala's next one): ~1 min each, $1.0m combined pool.
4. **Browser autofill profile** (Chrome/Firefox saved address + the existing tap-through page) for the 58
   captcha/error comps: ~45 s each instead of ~2 min; owner-in-the-loop, no bypass.
5. **One-time free accounts**: Flybuys/Velocity, Mouths of Mums, 7plus; 5 min each, then 1–16 comps.
6. **Social-only comps** (31 FB/IG): owner's own accounts, ~1 min each, mostly sub-$1k prizes.
7. **25-words-or-less** (18 comps): ~3 min each but far fewer entrants; pre-drafted lines in
   `data/entries/answers.json` cut it to ~1 min.
Not worth it: in-store / venue QR comps outside Melbourne; ING (customer-only); Flickerfest (film).
