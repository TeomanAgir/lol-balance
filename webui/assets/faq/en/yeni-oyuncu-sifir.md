# Why is my newly joined friend at ~8.33?

Everyone starts at ~8.33: **a neutral strength estimate minus full uncertainty.**

A new player's mu is 25 (neutral) and sigma is 8.33 (the system doesn't know
them at all yet). Since the score formula deducts uncertainty up front, the
starting score comes out at ~8.33:

```
25 − 2 × 8.33 ≈ 8.33
```

This is not a punishment — it is the system saying "I have no opinion yet".
With their first few matches, sigma drops quickly and the score settles at
their real level.
