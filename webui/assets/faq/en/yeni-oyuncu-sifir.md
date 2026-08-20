# Why is my newly joined friend at 0?

Everyone starts at 0: **a neutral strength estimate minus full uncertainty.**

A new player's mu is 25 (neutral) and sigma is 8.33 (the system doesn't know
them at all yet). Since the score formula deducts uncertainty up front, the raw
starting value comes out at 25 − 2 × 8.33 ≈ 8.33. The interface subtracts that
neutral value from every score, so the leaderboard shows exactly **0.0**:

```
raw       = 25 − 2 × 8.33 ≈ 8.33
displayed = 8.33 − 8.33 = 0.0
```

This is not a punishment — it is the system saying "I have no opinion yet".
With their first few matches, sigma drops quickly and the score settles at
their real level.

0 is a **starting line, not a floor**: scores can go negative, and that is
normal (part of the group currently sits below 0; the lowest score is ≈ −3.8).
A negative score is not a "bad player" label; it only says that this person's
current form sits a little below the neutral line.
