# Blind lotto test: pre-registration

Script: `analysis/lotto_blind.py`, sha256 prefix `9feda384dffdea12`. Scoring refuses to run if the script changes after this file is committed.

Blind draws: the last 25% of each game's draws, in date order. Methods, entries and metric are as documented in the script. Verdict: a method beats chance only if its blind-draw p-value is below 0.05 after Bonferroni correction across all 90 tests, in the direction of more matches.

| Game | Draws | Development draws | Blind draws (from) |
|---|---|---|---|
| Saturday Lotto | 1552 | 1164 | 388 (2019-05-25) |
| Weekday Lotto | 3138 | 2353 | 785 (2020-07-15) |
| Set for Life | 2412 | 1809 | 603 (2025-03-06) |
| Oz Lotto | 233 | 174 | 59 (2025-09-16) |
| Powerball | 446 | 334 | 112 (2024-09-12) |
