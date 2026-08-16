# Why is my newly joined friend at 0?

Everyone starts at 0: **a neutral strength estimate minus full uncertainty.**

A new player's mu is 25 (neutral) and sigma is 8.33 (the system doesn't know
them at all yet). Since the score formula deducts uncertainty up front, the
starting score comes out at exactly 0:

```
25 − 3 × 8.33 = 0
```

This is not a punishment — it is the system saying "I have no opinion yet".
With their first few matches, sigma drops quickly and the score settles at
their real level.
