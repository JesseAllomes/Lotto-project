# Every line against every draw: pre-registration

Script: `analysis/lotto_exhaustive.py`, sha256 prefix `c34f4f45dc02e58d`; uses `analysis/lotto_blind.py` (prefix `9feda384dffdea12`) for the games and the development/blind split. Scoring refuses to run if either changes after this file is committed.

Hit: a draw where the line matches 3+ winning main numbers. Tests 1-4 and the verdict are as documented in the script; the verdict rests on test 1 (top 1,000 development lines on the blind draws).

