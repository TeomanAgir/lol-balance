# How Is Your Score Computed? — Player Guide

> 🇹🇷 Türkçe: [rating_guide.md](rating_guide.md)
>
> This guide is for players; it is not the technical definition. The binding
> specification lives in `docs/rating_contract.md` (active engine:
> `openskill-pl-blend20-v1`).

That single number on the leaderboard isn't random: after every custom match it
is recomputed with the same rules, the same way for everyone. Here is the whole
kitchen, step by step.

## The big picture

**Score = 20% winning + 80% how you played − an uncertainty margin**

```
 20% W/L  |  80% Performance (KDA · damage · gold · CS · vision)
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
same scale as mu, then blended with **20% W/L + 80% performance** weights:

```
mu_eff = 0.2 × mu + 0.8 × (25 + 20 × (P_avg − 1))
SCORE  = mu_eff − 3 × sigma
```

"− 3 × sigma" means: the system **deducts up front** however much of your
strength it isn't sure about. That's why a player with few matches has a
suppressed score; as matches accumulate, sigma shrinks and your real strength
shows through. A player with no matches starts at exactly 0
(25 − 3 × 8.33 = 0) — which is why newcomers look neutral on the leaderboard.

## An end-to-end example

Take a player with 16 matches: mu = 26.29 (above 25 → a positive win/loss
balance), sigma = 7.36 (still plenty of uncertainty), P_avg = 1.27 (they play
27% above the match average).

```
mu_eff = 0.2 × 26.29 + 0.8 × (25 + 20 × 0.27)
       = 5.26 + 0.8 × 30.33 = 29.52

SCORE  = 29.52 − 3 × 7.36 = 7.45
```

Notice: 24.3 points of that score come from performance and 5.3 from W/L — but
22.1 points went to uncertainty. As this player keeps playing, sigma will drop
and their score will rise even if their play doesn't change at all.

## Role scores: the same math, a separate ledger per role

Alongside your main score, a **separate score** is kept for each role (TOP,
JUNGLE, MID, BOT, SUPPORT). The formula is exactly the same; the only
difference is that each role counts only **the matches you played in that
role**. For a match to enter the role ledger, all 10 players' roles must be
known and each team must have exactly one of each of the 5 roles.

**Team balancing uses these role scores:** when splitting 10 players into
teams, the system tries to place everyone in their strongest role while
searching for the fairest matchup. So if you're a monster on BOT but a tourist
in the JUNGLE, the system knows.

## Frequently asked questions

**We won but my score barely moved. Why?**
W/L is now only 20% of the score. Besides, if you beat a weak team, mu barely
rises anyway. What really moves your score is how your in-game performance
affects your career average (P_avg).

**We lost but my score went up. How?**
It can happen — it's a deliberate design decision. Mu drops, but if you played
very well that match, P_avg rises; the 80% performance side can outweigh the
20% W/L loss. In short: **playing well on the losing team is never wasted.**

**Can I farm stats to farm score?**
Only so far. Each component is capped at 2.0, the five components are
averaged, and team shares are relative: pointless farming shifts your team's
gold share toward you, but if it costs you the match, mu makes you pay. At
friend-group scale this risk was accepted.

**What happens if a match is voided?**
That match is removed from the books entirely and **the whole history is
recomputed** — as if it had never been played. The system is built to
reproduce the exact same result from scratch at any moment.

**Why is my newly joined friend at 0?**
Everyone starts at 0: a neutral strength estimate minus full uncertainty. With
their first few matches, the score quickly settles at their real level.
