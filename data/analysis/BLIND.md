# Blind lotto test: results

**Verdict: No method beat chance on the blind draws.**

Each method picked numbers using only earlier draws, and was scored only on blind draws it never saw (see BLIND_PREREG.md). Bonferroni threshold: p < 0.00056 (90 tests). *Edge* = matches above (or below) the exact random expectation, as a percentage.

| Game | Method | Entry | Blind draws | Matches | Expected | Edge | z | p | Beats chance |
|---|---|---|---|---|---|---|---|---|---|
| Saturday Lotto | hot_50 | games_24 | 388 | 7625 | 7449.6 | +2.4% | +0.71 | 0.479 | no |
| Saturday Lotto | hot_50 | system_24 | 388 | 1253 | 1241.6 | +0.9% | +0.50 | 0.615 | no |
| Saturday Lotto | hot_200 | games_24 | 388 | 7286 | 7449.6 | -2.2% | -0.66 | 0.509 | no |
| Saturday Lotto | hot_200 | system_24 | 388 | 1225 | 1241.6 | -1.3% | -0.73 | 0.464 | no |
| Saturday Lotto | hot_all | games_24 | 388 | 7537 | 7449.6 | +1.2% | +0.35 | 0.724 | no |
| Saturday Lotto | hot_all | system_24 | 388 | 1252 | 1241.6 | +0.8% | +0.46 | 0.646 | no |
| Saturday Lotto | cold_all | games_24 | 388 | 7199 | 7449.6 | -3.4% | -1.01 | 0.312 | no |
| Saturday Lotto | cold_all | system_24 | 388 | 1222 | 1241.6 | -1.6% | -0.86 | 0.387 | no |
| Saturday Lotto | overdue | games_24 | 388 | 7601 | 7449.6 | +2.0% | +0.61 | 0.541 | no |
| Saturday Lotto | overdue | system_24 | 388 | 1254 | 1241.6 | +1.0% | +0.55 | 0.584 | no |
| Saturday Lotto | repeat_last | games_24 | 388 | 7320 | 7449.6 | -1.7% | -0.52 | 0.601 | no |
| Saturday Lotto | repeat_last | system_24 | 388 | 1249 | 1241.6 | +0.6% | +0.33 | 0.744 | no |
| Saturday Lotto | pairs | games_24 | 388 | 7476 | 7449.6 | +0.4% | +0.11 | 0.915 | no |
| Saturday Lotto | pairs | system_24 | 388 | 1250 | 1241.6 | +0.7% | +0.37 | 0.711 | no |
| Saturday Lotto | momentum | games_24 | 388 | 7501 | 7449.6 | +0.7% | +0.21 | 0.836 | no |
| Saturday Lotto | momentum | system_24 | 388 | 1273 | 1241.6 | +2.5% | +1.39 | 0.166 | no |
| Saturday Lotto | least_picked | games_24 | 388 | 7423 | 7449.6 | -0.4% | -0.11 | 0.915 | no |
| Saturday Lotto | least_picked | system_24 | 388 | 1220 | 1241.6 | -1.7% | -0.95 | 0.341 | no |
| Weekday Lotto | hot_50 | games_24 | 785 | 15292 | 15072.0 | +1.5% | +0.62 | 0.532 | no |
| Weekday Lotto | hot_50 | system_24 | 785 | 2502 | 2512.0 | -0.4% | -0.31 | 0.756 | no |
| Weekday Lotto | hot_200 | games_24 | 785 | 15446 | 15072.0 | +2.5% | +1.06 | 0.289 | no |
| Weekday Lotto | hot_200 | system_24 | 785 | 2533 | 2512.0 | +0.8% | +0.65 | 0.515 | no |
| Weekday Lotto | hot_all | games_24 | 785 | 15166 | 15072.0 | +0.6% | +0.27 | 0.790 | no |
| Weekday Lotto | hot_all | system_24 | 785 | 2527 | 2512.0 | +0.6% | +0.47 | 0.642 | no |
| Weekday Lotto | cold_all | games_24 | 785 | 14679 | 15072.0 | -2.6% | -1.12 | 0.265 | no |
| Weekday Lotto | cold_all | system_24 | 785 | 2497 | 2512.0 | -0.6% | -0.47 | 0.642 | no |
| Weekday Lotto | overdue | games_24 | 785 | 15558 | 15072.0 | +3.2% | +1.38 | 0.168 | no |
| Weekday Lotto | overdue | system_24 | 785 | 2536 | 2512.0 | +1.0% | +0.74 | 0.457 | no |
| Weekday Lotto | repeat_last | games_24 | 785 | 15439 | 15072.0 | +2.4% | +1.04 | 0.298 | no |
| Weekday Lotto | repeat_last | system_24 | 785 | 2531 | 2512.0 | +0.8% | +0.59 | 0.556 | no |
| Weekday Lotto | pairs | games_24 | 785 | 15165 | 15072.0 | +0.6% | +0.26 | 0.792 | no |
| Weekday Lotto | pairs | system_24 | 785 | 2496 | 2512.0 | -0.6% | -0.50 | 0.620 | no |
| Weekday Lotto | momentum | games_24 | 785 | 15050 | 15072.0 | -0.1% | -0.06 | 0.950 | no |
| Weekday Lotto | momentum | system_24 | 785 | 2531 | 2512.0 | +0.8% | +0.59 | 0.556 | no |
| Weekday Lotto | least_picked | games_24 | 785 | 14940 | 15072.0 | -0.9% | -0.37 | 0.708 | no |
| Weekday Lotto | least_picked | system_24 | 785 | 2511 | 2512.0 | -0.0% | -0.03 | 0.975 | no |
| Set for Life | hot_50 | games_24 | 603 | 16290 | 16116.5 | +1.1% | +0.50 | 0.617 | no |
| Set for Life | hot_50 | system_24 | 603 | 2369 | 2302.4 | +2.9% | +2.22 | 0.026 | no |
| Set for Life | hot_200 | games_24 | 603 | 16290 | 16116.5 | +1.1% | +0.50 | 0.617 | no |
| Set for Life | hot_200 | system_24 | 603 | 2320 | 2302.4 | +0.8% | +0.59 | 0.557 | no |
| Set for Life | hot_all | games_24 | 603 | 16346 | 16116.5 | +1.4% | +0.66 | 0.508 | no |
| Set for Life | hot_all | system_24 | 603 | 2287 | 2302.4 | -0.7% | -0.51 | 0.609 | no |
| Set for Life | cold_all | games_24 | 603 | 16249 | 16116.5 | +0.8% | +0.38 | 0.702 | no |
| Set for Life | cold_all | system_24 | 603 | 2318 | 2302.4 | +0.7% | +0.52 | 0.602 | no |
| Set for Life | overdue | games_24 | 603 | 16150 | 16116.5 | +0.2% | +0.10 | 0.923 | no |
| Set for Life | overdue | system_24 | 603 | 2275 | 2302.4 | -1.2% | -0.91 | 0.362 | no |
| Set for Life | repeat_last | games_24 | 603 | 16151 | 16116.5 | +0.2% | +0.10 | 0.921 | no |
| Set for Life | repeat_last | system_24 | 603 | 2347 | 2302.4 | +1.9% | +1.49 | 0.137 | no |
| Set for Life | pairs | games_24 | 603 | 16328 | 16116.5 | +1.3% | +0.61 | 0.542 | no |
| Set for Life | pairs | system_24 | 603 | 2314 | 2302.4 | +0.5% | +0.39 | 0.698 | no |
| Set for Life | momentum | games_24 | 603 | 16165 | 16116.5 | +0.3% | +0.14 | 0.889 | no |
| Set for Life | momentum | system_24 | 603 | 2338 | 2302.4 | +1.5% | +1.19 | 0.235 | no |
| Set for Life | least_picked | games_24 | 603 | 16493 | 16116.5 | +2.3% | +1.09 | 0.278 | no |
| Set for Life | least_picked | system_24 | 603 | 2324 | 2302.4 | +0.9% | +0.72 | 0.471 | no |
| Oz Lotto | hot_50 | games_24 | 59 | 1459 | 1476.3 | -1.2% | -0.16 | 0.872 | no |
| Oz Lotto | hot_50 | system_24 | 59 | 201 | 210.9 | -4.7% | -1.04 | 0.296 | no |
| Oz Lotto | hot_200 | games_24 | 59 | 1561 | 1476.3 | +5.7% | +0.79 | 0.429 | no |
| Oz Lotto | hot_200 | system_24 | 59 | 221 | 210.9 | +4.8% | +1.07 | 0.286 | no |
| Oz Lotto | hot_all | games_24 | 59 | 1497 | 1476.3 | +1.4% | +0.19 | 0.846 | no |
| Oz Lotto | hot_all | system_24 | 59 | 216 | 210.9 | +2.4% | +0.54 | 0.590 | no |
| Oz Lotto | cold_all | games_24 | 59 | 1384 | 1476.3 | -6.2% | -0.86 | 0.389 | no |
| Oz Lotto | cold_all | system_24 | 59 | 205 | 210.9 | -2.8% | -0.62 | 0.534 | no |
| Oz Lotto | overdue | games_24 | 59 | 1421 | 1476.3 | -3.7% | -0.52 | 0.606 | no |
| Oz Lotto | overdue | system_24 | 59 | 215 | 210.9 | +1.9% | +0.43 | 0.665 | no |
| Oz Lotto | repeat_last | games_24 | 59 | 1501 | 1476.3 | +1.7% | +0.23 | 0.817 | no |
| Oz Lotto | repeat_last | system_24 | 59 | 205 | 210.9 | -2.8% | -0.62 | 0.534 | no |
| Oz Lotto | pairs | games_24 | 59 | 1586 | 1476.3 | +7.4% | +1.02 | 0.306 | no |
| Oz Lotto | pairs | system_24 | 59 | 214 | 210.9 | +1.5% | +0.33 | 0.743 | no |
| Oz Lotto | momentum | games_24 | 59 | 1396 | 1476.3 | -5.4% | -0.75 | 0.454 | no |
| Oz Lotto | momentum | system_24 | 59 | 196 | 210.9 | -7.1% | -1.57 | 0.116 | no |
| Oz Lotto | least_picked | games_24 | 59 | 1442 | 1476.3 | -2.3% | -0.32 | 0.749 | no |
| Oz Lotto | least_picked | system_24 | 59 | 218 | 210.9 | +3.4% | +0.75 | 0.453 | no |
| Powerball | hot_50 | games_24 | 112 | 3612 | 3763.2 | -4.0% | -0.98 | 0.328 | no |
| Powerball | hot_50 | system_24 | 112 | 541 | 537.6 | +0.6% | +0.29 | 0.773 | no |
| Powerball | hot_200 | games_24 | 112 | 3654 | 3763.2 | -2.9% | -0.71 | 0.480 | no |
| Powerball | hot_200 | system_24 | 112 | 535 | 537.6 | -0.5% | -0.22 | 0.826 | no |
| Powerball | hot_all | games_24 | 112 | 3778 | 3763.2 | +0.4% | +0.10 | 0.924 | no |
| Powerball | hot_all | system_24 | 112 | 539 | 537.6 | +0.3% | +0.12 | 0.906 | no |
| Powerball | cold_all | games_24 | 112 | 3715 | 3763.2 | -1.3% | -0.31 | 0.755 | no |
| Powerball | cold_all | system_24 | 112 | 546 | 537.6 | +1.6% | +0.71 | 0.476 | no |
| Powerball | overdue | games_24 | 112 | 3503 | 3763.2 | -6.9% | -1.68 | 0.092 | no |
| Powerball | overdue | system_24 | 112 | 525 | 537.6 | -2.3% | -1.07 | 0.285 | no |
| Powerball | repeat_last | games_24 | 112 | 3831 | 3763.2 | +1.8% | +0.44 | 0.661 | no |
| Powerball | repeat_last | system_24 | 112 | 540 | 537.6 | +0.4% | +0.20 | 0.839 | no |
| Powerball | pairs | games_24 | 112 | 3695 | 3763.2 | -1.8% | -0.44 | 0.659 | no |
| Powerball | pairs | system_24 | 112 | 555 | 537.6 | +3.2% | +1.48 | 0.140 | no |
| Powerball | momentum | games_24 | 112 | 3558 | 3763.2 | -5.5% | -1.33 | 0.184 | no |
| Powerball | momentum | system_24 | 112 | 530 | 537.6 | -1.4% | -0.64 | 0.519 | no |
| Powerball | least_picked | games_24 | 112 | 3788 | 3763.2 | +0.7% | +0.16 | 0.873 | no |
| Powerball | least_picked | system_24 | 112 | 544 | 537.6 | +1.2% | +0.54 | 0.587 | no |

## Current picks (for the next draw, by method)

- Saturday Lotto, hot_all: System 24 = 1 3 5 6 7 8 10 11 12 15 16 18 21 22 24 25 32 33 37 38 39 40 41 42
- Saturday Lotto, hot_50: System 24 = 2 3 8 9 10 11 12 13 15 17 19 20 22 27 28 30 31 32 33 36 40 41 43 44
- Saturday Lotto, overdue: System 24 = 3 4 5 6 7 8 10 12 14 17 19 21 23 24 25 26 27 28 29 34 35 36 37 38
- Saturday Lotto, least_picked: System 24 = 14 15 16 20 24 25 26 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45
- Weekday Lotto, hot_all: System 24 = 2 4 5 7 10 11 13 14 16 17 20 23 24 26 29 31 32 35 36 38 39 41 42 44
- Weekday Lotto, hot_50: System 24 = 1 2 6 7 8 11 12 14 17 18 22 24 25 28 30 31 33 34 36 37 39 42 43 45
- Weekday Lotto, overdue: System 24 = 1 4 5 6 7 8 10 13 15 16 17 19 21 22 23 24 26 28 35 36 38 40 41 44
- Weekday Lotto, least_picked: System 24 = 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
- Set for Life, hot_all: System 24 = 2 3 4 11 13 14 15 16 17 18 20 21 25 26 27 30 32 35 37 38 40 41 42 43
- Set for Life, hot_50: System 24 = 1 2 3 6 7 8 12 14 15 16 18 19 22 23 24 27 29 30 32 36 41 42 43 44
- Set for Life, overdue: System 24 = 1 4 5 6 9 10 12 14 16 20 21 22 23 24 26 28 29 31 34 36 37 39 40 41
- Set for Life, least_picked: System 24 = 14 16 20 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44
- Oz Lotto, hot_all: System 24 = 2 3 4 6 9 12 17 18 19 21 22 24 27 28 29 30 32 33 37 38 39 41 43 47
- Oz Lotto, hot_50: System 24 = 2 4 6 8 9 10 13 14 17 18 19 21 22 24 27 30 33 35 36 39 40 41 43 47
- Oz Lotto, overdue: System 24 = 2 3 4 7 9 10 11 15 16 18 20 23 24 26 27 28 30 31 37 39 43 44 45 47
- Oz Lotto, least_picked: System 24 = 4 14 16 25 26 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47
- Powerball, hot_all: System 24 = 1 2 3 4 6 7 9 11 12 14 15 16 17 18 19 20 22 23 25 27 28 30 32 34
- Powerball, hot_50: System 24 = 1 3 4 5 7 9 11 12 13 14 15 16 17 18 19 20 22 24 25 26 27 30 32 34
- Powerball, overdue: System 24 = 1 2 4 6 8 9 10 11 12 13 15 16 17 18 19 21 23 24 25 28 29 30 32 35
- Powerball, least_picked: System 24 = 1 4 5 6 12 14 15 16 18 20 21 22 23 24 25 26 28 29 30 31 32 33 34 35
