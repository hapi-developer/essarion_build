# Coding with LLMs

How to be effective when an LLM is in the loop — yours, an agentic CLI, or a teammate's. This skill is for the human in the seat.

- **Read every diff the AI produces before merging.** Models are confident even when they're wrong. The author of the PR is the human who hit "merge"; review accordingly.
- **Tight feedback loops beat clever prompts.** "Run the tests after every change" wins over "write a perfect prompt up front." The fastest signal — failing test, type error, lint — is the most useful one.
- **Scope discipline is on you.** The model will gladly refactor unrelated code, write tests for the framework, and generate types you didn't ask for. Be explicit about the *one* thing you want changed.
- **Anchor with concrete files and line numbers.** "Update `auth.py:42`" beats "fix the bug in auth." Specifics push the model into editing instead of explaining.
- **Don't trust generated regex / SQL / shell commands.** Three classes of code where a confident-sounding wrong answer takes the longest to debug. Test against real inputs.
- **Treat AI tests like AI code.** A model that wrote the function and the test for it can hide a bug in both. Eyeball the test for *what it actually checks*, not just "it's green."
- **Surface uncertainty.** Ask the model "what are you not sure about?" — the answer is usually genuine and saves a regression.
- **Reject elegant rewrites of working code.** A one-line bug fix is a one-line PR. Don't accept a 200-line refactor packaged with it; that's two PRs at minimum.
- **Big context, focused task.** Pull in the relevant files; ask for the smallest possible change. "Here are five files; change *this one line* in one of them."
- **Verify external claims.** API names, library behaviors, RFC clauses, CVE numbers. The model hallucinates these confidently; a one-minute search costs nothing.
- **Commit messages are yours to write, even when the code isn't.** A model can suggest one; you should know enough about the change to evaluate the suggestion.
- **Tool use needs guardrails.** When the model can run shell, edit files, or hit APIs, every action has a real consequence. Allow-lists; dry-run modes; human-in-the-loop on irreversible operations.
- **Cost watching: a session can burn $50 if you blink.** Per-call budgets, per-session totals, and an alert when you hit them.
- **The model is a force multiplier, not a substitute.** If you don't understand the problem, the model won't either — it'll just sound like it does. Understanding scales the speedup.
