# Automated code review in CI

essarion build can review every pull request — and, uniquely, get an
**independent cross-model second opinion** on each change. Two different model
families review the diff; where they disagree is where bugs hide. This is the
same `/crosscheck` capability the interactive agent uses, exposed as a
CI-friendly command.

## The `review` command

```bash
# Review the working-tree diff (markdown to stdout)
essarion-build review

# Review a PR against its base, with a second model cross-examining
essarion-build review \
  --base origin/main \
  --provider openrouter \
  --model openai/gpt-4o-mini \
  --crosscheck-model anthropic/claude-haiku-4-5

# Review an explicit diff file, emit JSON, gate the build on disagreement
git diff origin/main...HEAD > pr.diff
essarion-build review --diff pr.diff --crosscheck-model anthropic/claude-haiku-4-5 \
                      --fail-on-disagree --json
```

Diff source resolution: `--diff FILE` (or `--diff -` for stdin) wins; otherwise
`git diff <base>...HEAD` when `--base` is given; otherwise the working-tree
`git diff`.

| Flag | Meaning |
|---|---|
| `--diff FILE` | Diff to review (`-` reads stdin) |
| `--base REF` | Review `git diff <REF>...HEAD` (PRs) |
| `--goal TEXT` | What the change is meant to accomplish (sharpens the review) |
| `--repo DIR` | Repo dir for context + git (default: `.`) |
| `--crosscheck-model M` | A **different** model that independently red-teams the change |
| `--fail-on-disagree` | Exit `3` when the second model raises concerns (gate CI on it) |
| `--provider` / `--model` / `--max-tokens` | Standard model overrides |
| `--skill` / `--no-skills` | Override the review skill set |
| `--json` | Emit JSON instead of markdown |

Cost is bounded by design: the second opinion sees only the goal + a windowed
diff (a few hundred output tokens), never the whole repo.

## GitHub Action

A ready-to-use workflow ships in
[`examples/github-action-review.yml`](../examples/github-action-review.yml).
Copy it to `.github/workflows/essarion-review.yml`, add an `OPENROUTER_API_KEY`
secret, and every PR gets a review comment that updates in place. The relevant
step:

```yaml
- env:
    OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
  run: |
    essarion-build review \
      --base "origin/${{ github.base_ref }}" --repo . \
      --provider openrouter --model openai/gpt-4o-mini \
      --crosscheck-model anthropic/claude-haiku-4-5 > review.md
```

One OpenRouter key reaches both the builder and the reviewer models. Prefer
going direct? Set `--provider anthropic` (etc.) and the matching secret.

## Scheduled reviews & audits

For recurring, unattended checks (nightly dependency audit, weekly "what
changed" digest), use the scheduler and let cron drive it:

```bash
essarion schedule add "audit dependencies for known CVEs and summarize" --every 1d
# crontab: run whatever is due every 10 minutes
*/10 * * * * cd /path/to/repo && essarion schedule run-due >> .essarion/cron.log 2>&1
```

See the project README for the full `schedule` surface.
