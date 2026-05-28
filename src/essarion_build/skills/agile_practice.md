# Agile practice

Process is a tool, not a goal. These are the techniques that consistently work; ignore the rest.

- **Working code over working documents.** A demoed feature, even if rough, beats a perfect spec. Iterate on the running system, not on the spec describing it.
- **Smallest releasable change.** What's the *least* you can ship that delivers value and lets you learn? Usually smaller than your first instinct. Slicing aggressively forces design.
- **Time-box estimates, not commit-to-them.** "About a week" is a reasonable signal; "5.0 days" is fiction. Use estimates to decide if a task fits; don't use them as deadlines.
- **Stand-ups have one purpose: surface blockers.** Three sentences each: yesterday, today, blocker. If yours is becoming a status report meeting, kill it or shorten it.
- **A retro that doesn't change anything is a meeting.** Retro outputs must be concrete action items with owners and dates. "We should communicate more" is not an action item.
- **WIP limits are real.** Doing five things at once means doing five things slowly and badly. Three or fewer in flight per person; finish before starting.
- **The backlog is not a wishlist; it's a forecast.** If it's longer than ~30 items, you're hoarding. Prune mercilessly; close stuff nobody will pick up. Real prioritization beats theoretical inclusion.
- **Definition of Done is part of the work.** Tests pass, docs updated, deployed, monitored. If your team's DoD is "merged to main", things will rot in staging.
- **Demo to the people who'll use it.** Stakeholders, customers, downstream teams. Internal-only demos miss the feedback that matters.
- **Story points are a wrist-watch, not a stopwatch.** They measure rough size, not time. Don't conflate; don't track individual velocity (a perverse incentive).
- **Spike when uncertainty dominates.** A 1-day, no-commit-to-ship time-box to learn enough to estimate. Saves a week of guesswork.
- **Pre-mortems beat retros.** Before a risky change: "Imagine this fails. How does it fail?" The team's intuition surfaces risks the plan missed.
- **The tracking tool is a tool, not the process.** Jira / Linear / Notion are records of decisions; the decisions happen in conversation. Don't optimize the tool over the work.
- **Async by default.** A Slack thread can capture a decision a meeting wouldn't. Reach for sync only when latency genuinely matters (incidents, design tradeoffs).
- **Calibrate via metrics.** Cycle time (PR open → merged), defect rate per release, on-call pages per week. Anecdotes tell stories; metrics tell trends.
