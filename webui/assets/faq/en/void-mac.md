# What happens if a match is voided?

That match is removed from the books entirely and **the whole history is
recomputed** — as if it had never been played.

This is a core principle of the system: raw match records are never modified,
and the rating can be reproduced from those records from scratch at any moment.
After a void, everyone's mu, sigma and P_avg are recomputed by replaying the
remaining matches in order; the leaderboard updates accordingly.

That is why voiding is irreversible and the match history screen asks for
confirmation first.
