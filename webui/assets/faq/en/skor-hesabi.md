# How is your score computed?

> This guide is for players; it is not the technical definition. The binding
> specification lives in `docs/rating_contract.md` in the repository (active
> engine: `openskill-pl-blend30-s2-v1`).

That single number on the leaderboard isn't random: after every custom match it
is recomputed with the same rules, the same way for everyone. Here is the whole
kitchen, step by step.

## The big picture

**Score = 30% winning + 70% how you played − an uncertainty margin**

```
 30% W/L  |  70% Performance (KDA · damage · gold · CS · vision)
```

Blending these two produces an "effective strength"; the system then subtracts
however much it is still unsure about you. Few matches = a cautious score.

## 1. The win/loss core: mu and sigma

At the foundation sits a skill model called **OpenSkill** (a relative of chess
ELO, evolved for team games). It tracks two numbers per player:

- **mu (μ)** — the system's estimate of your strength. Everyone starts at 25.
  It **goes up when you win, down when you lose**. How much depends on the
  opposition: beat a strong team and you gain a lot; lose to a weak team and
  you lose a lot.
- **sigma (σ)** — how **uncertain** the system is about that estimate. Everyone
  starts at 8.33; it shrinks a little with every match. A player with many
  matches has a small sigma: the system knows them by now.

> Important detail: individual performance plays no part in this step. mu looks
> only at the match result (and the strength of the two teams). "I played well
> but we lost" won't save you here — that's what the next steps are for.

## 2. The match performance score: how good were you in that game?

After every match, your play is measured **relative to the 10 players in that
match**. There are five components; each one is "your ratio to the match
average" — 1.0 means exactly average:

| Component | What it measures | Compared against |
|---|---|---|
| KDA | (kills + assists) / deaths | the average of the 10 players in the match |
| Damage share | your share of your team's champion damage | the equal share of 20% |
| Gold share | your share of your team's gold | the equal share of 20% |
| CS/min | minions per minute | the match average |
| Vision | vision score | the match average |

Five different metrics were chosen deliberately: damage and gold catch the
carry, vision catches the support, KDA catches everyone. That way no single
role gets a systematic advantage.

Each component is **clamped between 0.5 and 2.0** (one crazy stat line can't
send your score to the moon), then the average of all of them is taken. The
result is that match's **performance score**: 1.0 = an average player, 1.3 =
among the best in the match, 0.7 = a bad night.

> If a stat is missing from the record (e.g. an old, manually entered match),
> that component is simply skipped; if none are available, the score is treated
> as neutral (1.0). Nobody gets punished for missing data.

## 3. Career performance: P_avg

The **average** of your performance scores across all valid matches. This is
called P_avg. One legendary game won't carry you, and one disaster won't sink
you — consistency wins.

## 4. The blend and the visible score

Now the two worlds merge. First the performance average is converted to the
same scale as mu, then blended with **30% W/L + 70% performance** weights:

```
mu_eff = 0.3 × mu + 0.7 × (25 + 20 × (P_avg − 1))
SCORE  = mu_eff − 2 × sigma
```

"− 2 × sigma" means: the system **deducts up front** however much of your
strength it isn't sure about. That's why a player with few matches has a
suppressed score; as matches accumulate, sigma shrinks and your real strength
shows through. For a player with no matches the raw value is
25 − 2 × 8.33 ≈ 8.33.

> **Display note — a 0 baseline:** The formula itself hasn't changed (the
> 30%/70% blend and − 2 × sigma are the same), but the interface **subtracts
> that neutral value (≈ 8.33) from every score** before showing it. So a player
> with no matches reads exactly **0.0** on the leaderboard and scores are again
> read from a 0 baseline. This is only a display shift: the ranking, the gaps
> between players and per-match changes like "+0.35" are unaffected (the shift
> cancels out in a difference).
>
> A natural consequence: **negative scores are normal.** Anyone below the
> neutral line reads as negative — part of the group is there today, with the
> lowest score at ≈ −3.8. A negative score is not a "bad player" label; it only
> says that this person's current form sits below neutral.

## An end-to-end example

Take a player with 16 matches: mu = 26.29 (above 25 → a positive win/loss
balance), sigma = 7.36 (still plenty of uncertainty), P_avg = 1.27 (they play
27% above the match average).

```
mu_eff    = 0.3 × 26.29 + 0.7 × (25 + 20 × 0.27)
          = 7.89 + 0.7 × 30.40 = 29.17

RAW       = 29.17 − 2 × 7.36 = 14.45
DISPLAYED = 14.45 − 8.33 = 6.12
```

Notice: 21.3 points of that raw value come from performance and 7.9 from W/L —
but 14.7 points went to uncertainty. The **6.12** you see on screen is that raw
value measured against the neutral line (≈ 8.33). As this player keeps playing,
sigma will drop and their score will rise even if their play doesn't change at
all.

## Role scores: the same math, a separate ledger per role

Alongside your main score, a **separate score** is kept for each role (TOP,
JUNGLE, MID, BOT, SUPPORT). The formula is exactly the same; the only
difference is that each role counts only **the matches you played in that
role**. For a match to enter the role ledger, all 10 players' roles must be
known and each team must have exactly one of each of the 5 roles. Role scores
use the same display shift: a role you have never played reads **0.0**.

**Team balancing uses these role scores:** when splitting 10 players into
teams, the system tries to place everyone in their strongest role while
searching for the fairest matchup. So if you're a monster on BOT but a tourist
in the JUNGLE, the system knows.
