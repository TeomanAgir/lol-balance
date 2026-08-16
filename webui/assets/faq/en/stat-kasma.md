# Can I farm stats to farm score?

Only so far. Each component is **capped at 2.0**, the five components are
averaged, and team shares are relative: pointless farming shifts your team's
gold share toward you, but if it costs you the match, mu makes you pay. At
friend-group scale this risk was accepted.

## Why do the clamp bounds (0.5 – 2.0) exist?

- **Ratio metrics explode in stomps.** Ratio-based components like KDA easily
  shoot to absurd values in one-sided matches (e.g. 20 kills on 1 death).
  Without the clamp, a single stomp would dominate the average of months of
  matches.
- **One match must not hijack P_avg.** P_avg is a career average; thanks to
  the upper bound, a single legendary night can move it only so much.
  Consistency is worth more than one-off fireworks.
- **Farming a single stat has a mathematical ceiling.** A component counts as
  at most 2.0; averaged over five components, that means maxing out one stat
  contributes **at most +0.2** to the match performance score. The real way to
  raise your score is playing well across the board, not inflating one counter.
- **The score band stays predictable.** Because the performance score always
  sits between 0.5 and 2.0, the range your score can move in is known; nobody
  rockets off the leaderboard on one match.
- **The lower bound is deliberately soft.** The floor is 0.5: the penalty for
  a bad night (at most −0.1 per component) is lighter than the reward for a
  good one (at most +0.2). A disaster match doesn't go unpunished, but it
  won't sink you either.
