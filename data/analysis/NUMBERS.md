# Lotto number sets

From `analysis/lotto_numbers.py` over each game's current-format draws (see that file for the method).

- **Least picked**: the numbers fewest players choose. Same chance of winning; fewer people to share a
  prize with, so each win pays more. *Uplift* is the estimated extra paid on a division win.
- **Most drawn**: the numbers drawn most often. *p* tests whether the counts fit equally likely numbers;
  p above 0.05 means they do, and past frequency says nothing about the next draw.
- *Holdout r*: how well popularity fitted on the earlier half of draws predicts the later half (0 = not
  at all, 1 = perfectly). Positive and clear of zero means the popularity pattern is stable.

| Game | Draws (from) | Least picked | Uplift | Holdout r | Most drawn (draws counted) | Chi-square p |
|---|---|---|---|---|---|---|
| Saturday Lotto | 822 (2011-01-29) | 37 38 39 41 43 44 | +38% | 0.66 | 1 5 6 11 22 42 (1552 from 1997) | 0.08 |
| Mon/Wed/Fri Lotto | 384 (2024-05-20) | 37 38 39 41 42 43 | +51% | 0.33 | 11 15 17 22 26 36 (384 from 2024) | 0.36 |
| Oz Lotto | 233 (2022-05-17) | 39 40 41 42 43 46 47 | +26% | 0.55 | 4 17 19 21 30 39 47 (233 from 2022) | 0.86 |
| Powerball | 446 (2018-04-19) | 1 14 15 20 30 32 34 | +24% | 0.18 | 3 7 9 11 14 17 18 (446 from 2018) | 0.94 |
| Set for Life | 2412 (2020-03-23) | 38 39 40 41 42 43 44 | +46% | 0.51 | 2 13 15 27 37 40 41 (2412 from 2020) | 0.60 |

Popularity rank 1 = least picked. Powerball's Powerball number is not modelled here.
