# LLM integration

- **Treat the model as a black box that occasionally lies.** Never let model output cross a security boundary without validation. Untrusted input + untrusted output: validate both ends.
- **Prompt injection is the #1 risk.** Anything user-supplied can override your system instructions. Mitigations: structured input (JSON in, JSON out), separate instruction channels from data channels, never grant the model unconstrained tool access on untrusted input.
- **Structured outputs over freeform.** Ask for JSON / XML tags / tool calls. Parse on the way out; reject (or re-prompt) on schema mismatch. This is the easy half of preventing hallucinated fields slipping into downstream systems.
- **Tool use needs explicit allow-lists.** Don't let the model choose any shell command, any HTTP URL, any DB query. List the tools, their input schemas, and their side-effect categories. Human-in-the-loop for irreversible actions.
- **Cache aggressively where output is stable.** Prompt caching (Anthropic), context caching (Gemini), or a content-addressed local cache. Re-running the same prompt should be cheap.
- **Token budget is a real budget.** Estimate per-call cost; cap the context size; truncate older messages with a known policy (summarize vs. drop). Surprise bills come from unbounded context.
- **Hallucinations are facts you can't trust without grounding.** RAG, citations, structured database lookups — give the model *somewhere to look*. Verify any claim that affects a decision.
- **PII handling: redact before the model sees it.** Logs leak, vendors archive, prompts get cached. Tokenize sensitive fields; never let the model see customer PII it doesn't need.
- **Latency is the UX.** Streaming (token-by-token) is the standard. Show partial output as it arrives; never block the user on a 30s round trip.
- **Evals matter more than vibes.** Build a benchmark of 100 representative inputs with expected behavior. Run it on every prompt change. Without it you're vibe-coding in a non-deterministic system.
- **Cost / latency / quality is a triangle, pick two.** Cheap fast model + reasoning amplification (e.g. plan→draft→selfcheck) often beats expensive single-shot for coding tasks.
- **Idempotency for write-effecting tool calls.** Models retry; tools must dedupe. An idempotency key passed by the orchestrator is the standard solution.
