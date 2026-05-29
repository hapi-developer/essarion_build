# Incident response

- **Mitigate first, root-cause second.** When the site is on fire, the priority is putting out the fire — roll back, kill the flag, drain the bad node. Forensics waits.
- **Declare incidents early.** When in doubt, page. Small incidents that turn out to be nothing cost a meeting; missed incidents cost a weekend (and trust).
- **Clear roles: Incident Commander, Communications, Operations.** One IC at a time. IC delegates and decides; doesn't try to fix it themselves. (For small incidents, one person can wear multiple hats — but make the role explicit.)
- **Single channel, single thread.** All comms in one Slack channel (or equivalent). All status updates from the IC. Out-of-band guesses by the curious are noise, not help.
- **Status updates on a clock.** Every 30 minutes minimum, even if the update is "still investigating, next update at HH:MM". External: customers want frequency, not detail.
- **Customer comms during the incident.** Acknowledge, set expectation, update. Status page first, then targeted notifications. Don't speculate on causes ("appears to be a database issue") until you're sure.
- **Postmortem within a week. Blameless.** Timeline (UTC, precise to the minute), what happened, why, why was it not caught, action items (owned, dated). The point is system change, not punishment.
- **Action items have owners and deadlines** or they don't exist. "Improve monitoring" is not an action item; "@alice adds CPU alert by Friday" is.
- **Severity levels are calibrated, not subjective.** SEV1 = data loss / total outage / revenue stop. SEV2 = significant degradation. SEV3 = isolated bug. Publish the criteria; everyone agrees in advance.
- **Pre-mortems > postmortems.** Before a risky change: "if this fails, how does it fail?" Cheaper to ask in advance than to learn in production.
- **Practice the drill.** Game days, chaos engineering, recovery rehearsals. The first time you run the runbook should not be during the actual outage.
