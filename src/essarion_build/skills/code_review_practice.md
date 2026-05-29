# Code-review practice

How to give *and* receive code review well — companion to `code_review`, which covers what to look at.

- **Approve when you'd be comfortable shipping the code.** Not "perfect." "Good enough that I'd ship it." Letting perfect be the enemy of good blocks everyone.
- **Big PRs hide bugs.** A 1000-line PR gets a rubber-stamp review; a 100-line PR gets a careful one. Push back on size; suggest splitting. The author owns the split, not you.
- **Differentiate "nit", "question", "blocker".** Mark every comment. Nits are optional cleanups; questions need an answer but not a fix; blockers stop the merge. Without labels, every comment looks like a blocker.
- **Suggest, don't dictate.** "Could we use `Path` here? It avoids the string-split." beats "Use Path." Authors push back on dictates; they engage with suggestions.
- **Show, don't tell.** GitHub suggestion blocks let you propose the exact replacement. Less argument, less re-review.
- **Praise good code visibly.** "Nice — this is much clearer than the old shape." costs nothing and improves the team. Review is also where culture is built.
- **Ask for tests, but accept "I tested this manually" when honest.** Some changes are hard to test. Stating *how* a change was verified is a substitute for an automated test.
- **Don't review at the wrong altitude.** "This whole approach is wrong" two days into the PR is too late. If the design needs discussion, *have it before the PR exists* — comment on the design doc, the issue, or in chat.
- **Tag who you want to review.** A team `@auth-team` review is everyone's job, which is no one's job. Assign individuals; rotate the load.
- **As an author: pre-review your own diff.** Read it like you didn't write it. Half your reviewer comments will be ones you'd have made yourself.
- **Respond to every comment.** Even "fixed in [commit hash]" closes the loop. Silence forces the reviewer to re-read every thread to figure out what's done.
- **A PR is not a fight.** When you disagree, propose the right next step ("let me jump on a call to clarify", "I'll send a follow-up PR for that"). Don't dig in for sport; you and the reviewer both want the same thing.
- **Review fast for small things, slow for big things.** A typo fix should be reviewed in ten minutes. A new module should marinate. Match speed to risk.
- **Re-review your own changes after sleep.** The "obvious bug" you missed is the one your fresh eyes catch in the morning. Push, sleep, glance again before the reviewer wakes.
- **Be specific in approval.** "LGTM" is fine for trivial PRs; for a 500-line PR, a line about what you actually verified ("I checked the migration handles existing rows; I trust the test suite for the rest") shows your work.
