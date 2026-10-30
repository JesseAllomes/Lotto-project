# Opportunity hunt: legal player-favourable situations (Victoria), 30 Oct 2026

Labels: **measured** = computed from data in this repo or from pages fetched today; **sourced** = read from a
promoter's or operator's published page; **estimated** = my assumption, stated. Face value = promoter's stated
prize value; prize homes need a haircut (selling costs, furniture resale, valuation optimism; I use 10%).

Short answer: the Lott draw games add nothing to SURVEY.md (Lucky Lotteries above $35.0M/$27.2M remains the
only Lott-sold product that has ever been positive EV). The new material is in capped charity lotteries, where
bundle pricing plus a one-time doubling offer gives a first purchase an expected value well above its price.

## Ranked list

### 1. Endeavour Foundation prize-home lottery: $100/$200 books, and the one-time "first tickets doubled" offer

- **What.** Endeavour Lotteries (QLD charity, Vic permit MG-R26349394) sells books where most tickets are
  bonus tickets: $100 = 30 tickets, $200 = 60 tickets ($3.33 each) versus $10 for a single ticket (sourced:
  draw 471 page). Lottery 471 prize is $3,329,295 total, of which the Little Mountain house is $3,150,000
  "market value April 2026" plus $10,000 gold and furnishings; drawn 18 Feb 2027. Lottery 470 ($3.43M
  Mooloolaba, cap 1.5M tickets) closes 10 Dec 2026.
- **Why the odds favour the player.** The terms fix the ticket count: "The number of tickets available will
  range from 600,000 (single-ticket purchases) to 1,350,000 (if bundle purchases occur)" (sourced, lottery 471;
  470: 670,000 to 1,500,000). Real issue is below the cap: the results pages embed every winning ticket number
  (`winnerTicketNumber` in the page JSON). Draw 469 ($2.9M): 72 numbers, lowest 29,262, highest 984,753.
  Draw 467 ($2.8M): 86 numbers, lowest 10,183, highest 875,031 (measured). Tickets are numbered from ~1, so the
  highest winning number is a hard lower bound on tickets issued; a German-tank estimate puts the total near
  1.0-1.05M. EV of a $200 book (60 tickets) on the 471 prize: 101% of face at N = 985k, 95% at N = 1.05M, 74% at
  the 1.35M cap (measured/estimated). Odds of the house: 1 in ~17,500 per $200.
- **The edge.** The membership sign-up banner on the same page reads "SIGN-UP BONUS: Your 1 ticket -> 2
  tickets (one-time only offer) ... Join now and your first tickets will be DOUBLED at no extra cost"
  (sourced, page HTML; the published membership T&Cs, last updated 12 Jan 2023, do not mention it, so confirm
  at sign-up that it applies to the $100/$200 book). Doubled, a $200 book is ~120 tickets: EV ~190-200% of face,
  ~170-180% after a 10% house haircut, i.e. about +$150 expected on $200, with a 1 in ~8,750 chance of a $3M
  house and a 99.99% chance of losing $200. Membership has no lock-in and is cancelled by phoning 1800 63 40 40
  (sourced); without the doubling, repeat books run ~85-95% after haircut, so cancel after the first charge
  unless a double-ticket promotion is on (past promo pages: "452 204 Double Bonus Offer", "453 205 Early Bird
  Promo").
- **Cost.** $100-$200 once (plus the first monthly membership charge, which is itself the ticket purchase).
- **Risks.** Offer wording may change or exclude large books; Endeavour "may in its absolute discretion apply
  for additional tickets" (cap rise); a sold-out draw rolls your order into the next lottery; the house is in QLD
  (agent fees, land tax if held, resale of furniture at a fraction of $150k, valuation may be high); bonus draws
  are drawn from purchase windows, so only the maximum winning number, not the median, is used for N.
- **Monitor (token-free).** New worker `workers/sellthrough.py`: after each Endeavour/RSL/Mater/yourtown draw,
  fetch the draw page, pull all `ticketNumber`/`winnerTicketNumber` values and the cap clause, store
  `date, draw, prize, cap, winners, max_ticket, N_hat` in `data/comps/sellthrough.csv`; from the live draw page
  JSON (`numTickets`/`price` per book) compute EV per book and open an issue when any book exceeds 100% of
  face, or when a doubling promo appears.

### 2. Saturday Lotto $20M Superdraw / $30M Megadraw: sales are falling toward break-even

- **What.** Division 1 is fixed from the Prize Reserve regardless of sales. Measured from the 822-draw register:
  Superdraw realised RTP was 0.45-0.49 in 2011-2019 (median ~105M games) and 0.67, 0.68, 0.67, 0.70, 0.73,
  0.76 in 2021-2026 as games fell to 58M (2026 median); the 26 Jul 2025 $30M Megadraw hit 0.83 at 72M games, the
  highest ex-ante RTP of any Lott draw in the register.
- **Break-even** (prizes = 0.6725 x 0.6 x subscriptions + Div 1; retail = subscriptions / 0.889): 32.8M games for
  $20M, 49.2M for $30M, 65.7M for $40M (measured formula). At the 2021-26 decline (~3%/yr) that is ~15-20 years
  away, so this is a watch item, not a plan. With the least-picked numbers from NUMBERS.md (+38% on the Div 1
  share) a 2026 Superdraw is ~0.90 (estimated): the best ordinary Lott ticket, still negative.
- **Monitor.** Add games-sold (= prize fund / 0.6 / $0.845) per draw to the draws worker and alert when any
  Superdraw sells under 40M games.

### 3. Bonus draws tied to short purchase windows (charity lotteries)

- **What.** Promoters run side draws restricted to tickets bought in a window: yourtown "$5K Boo-nus Draw" for
  tickets bought 29-31 Oct 2026 (sourced); Endeavour's 469 results show 30 of 72 winners inside one tenth of
  the ticket-number range, i.e. a draw over a purchase window (measured). A ticket bought inside the window is in
  a pool a tenth or less of the main draw.
- **Value.** Small: a $5,000 draw over ~3 days of yourtown sales (~15k tickets, estimated) is ~$0.33 per ticket
  on a ~$15 ticket. Only worth timing a purchase you were making anyway. Monitor: `sellthrough.py` can log bonus
  draw names, windows and prizes from the same JSON.

### 4. Royal Melbourne Hospital Home Lottery add-ons and early birds (Victoria)

- The 2026-3 home lottery sold out before its 15 Oct draw ($5.3M grand prize, 5,011 prizes, $500k early bird,
  free membership draw; sourced). Ticket price and count are not on the page, so EV is unknown; older coverage
  says ~1 in 15 to win a prize. Cash Calendar ($25, $150k gold over 6 draws) and Holiday for Life ($15, $100k
  gold alternative) are open to 13 Nov 2026; value depends on unpublished sales. One-off manual read of the
  Vic permit terms (maximum tickets) would settle it; otherwise not rankable.

### 5. Daily and unlimited-entry competitions: persistence multiplies your share

- odds.csv has 10 daily, 4 weekly and 8 unlimited-entry comps open to Vic, including three $100,000 cash comps
  closing 1 Nov 2026 (ids 73682, 73712, 73803, free entry). Entering every day of a 60-day window gives ~60
  entries against the typical entrant's 1-5 (estimated: entrant counts are never published), a 10-60x better
  chance at zero cost. Monitor/act: have `entry_queue.py` re-queue `entry_limit=daily` comps each day instead of
  once.

### 6. Instant-win "winning moment" promotions

- 20 instant comps are open (18 purchase-required). Where terms award a prize to the first entry after a random
  time, entries lodged in low-traffic hours face less competition per entry (estimated; no entrant data). Only
  for receipts you already have.

## Checked and ruled out

- RSL Art Union AU435L ($14.7M): $100 book = 50 tickets (10 paid + 40 bonus). Draw 434 ($10.2M) lists 9,995
  winning numbers, uniform across 1 to 19,098,836, so ~19.1M tickets were issued: ~27% of face per $100 book
  (measured). The 10,763,970 "cap" in the AU435L terms is below 434's issue, so it does not bind; expect 30-35%.
- Mater Prize Home 328: $7.1M / 30.1M cap at $1/ticket = 24% at the cap (measured from terms).
- Mater Cars for Cancer 132: $507,792 / (84,632 x $30) = 20% (measured). Mater Dollar Dream Ticket: $100k over
  up to 1M tickets at >= $0.50 = <= 20%.
- yourtown Buderim ($2.88M, cap 500k): $5.76 per ticket, ~38% at the usual $15 ticket (price estimated);
  Range Rover draw $381k / 180k = $2.12 per ticket. No bonus-ticket books seen.
- Oz Lotto: ex-ante RTP reconstructed from the register (carried Div 1 + 40% of each prize fund, sharing by
  games sold) peaks at 0.82 (26 Dec 2023, ~$98M, 103M games) and 0.77 (4 Feb 2025); Powerball peaks at 0.74
  (1 Feb 2024, 275M games) (measured). Realised >100% only ex post with a lone winner.
- Weekday Windfall: realised RTP median 0.29; CashCade 0.41 (max 0.83); DoubleDivs 0.38 (measured). Set for
  Life ~40% (SURVEY). Saturday Lotto $10M "Jackpot" weeks 0.60-0.76 (measured).
- Keno Mega Millions: break-even $10.6M never reached (SURVEY); nothing new.
- Instant Scratch-Its: The Lott publishes only aggregate 2025 win statistics (76.87M tickets), no per-game
  prizes-remaining ledger (sourced), so US-style ledger play is impossible.
- The Lottery Office (legal matched tickets): EuroMillions' cap roll-down and UK Lotto must-be-won draws are
  genuine roll-down mechanics, but per-game AUD prices are not on the landing page ("from $3.70") and US games
  lose 24% federal + up to 8% state withholding on an annuity-advertised jackpot (sourced); estimated well under
  100% even at record jackpots. Would need a price check before a final verdict.
- LMCT+ and giveaway clubs: $19.99-$99.99/month tiers (2024 reporting), prize total versus revenue unpublished;
  no basis for a player edge.
- RSL VIP $50K Weekly Cash Giveaway: nine or more $50k draws per cycle restricted to direct-debit VIPs; pool size
  unpublished, cannot be valued.
- Lotto Strike (NSW/ACT only), syndicates (priced at exact share), office sweeps (zero-sum), bookmaker
  promotions (out of scope; Victoria bans sign-up inducements), lottery betting (illegal since 2019).
- Number prediction: not pursued (BLIND.md, BLIND_FIXED.md).

## Method notes

- Lott RTPs: `analysis/lotto_numbers.prize_fund()` per draw; games = fund / fund-share / ($retail x 0.889);
  realised RTP = sum(winners x dividend) / (games x retail); ex-ante adds jackpot x (1 - e^-lambda).
- Charity sell-through: regex over the draw page HTML for `"ticketNumber"`/`"winnerTicketNumber"`; N lower
  bound = max; estimate = max x (k+1)/k using only full-population draws.
