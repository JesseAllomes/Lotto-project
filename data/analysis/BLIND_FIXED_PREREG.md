# Blind lotto test, fixed sets: pre-registration

Script: `analysis/lotto_blind_fixed.py`, sha256 prefix `e917ce0bd3328311`; uses `analysis/lotto_blind.py` (prefix `9feda384dffdea12`). Scoring refuses to run if either script changes after this file is committed.

Same games and blind draws as BLIND_PREREG.md. Each set is chosen once from the development draws and played on every blind draw. Verdict: beats chance only if p < 0.05 after Bonferroni across 40 tests, in the direction of more matches.

