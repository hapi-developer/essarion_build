# Privacy & data handling

_Effective date: July 10, 2026_

`essarion-build` is an open-source, bring-your-own-key (BYOK) SDK and CLI
coding agent published by **Essarion** under the Apache License 2.0. This
note explains what it does — and does not — do with your data. It is not a
terms-of-service for a hosted product; your rights in the software itself are
governed by the [LICENSE](./LICENSE).

## The short version

- **It runs on your machine.** `essarion-build` is a local library and CLI.
  Essarion operates no server for it and **receives no data from it**.
- **No telemetry, analytics, or "phone home."** The package sends nothing to
  Essarion. It never imports a logging or telemetry service by default.
- **BYOK — your data goes only where you point it.** Your prompts, code, repo
  context, and files are transmitted only to the model provider(s) and tools
  **you** configure with **your** keys.

## Where your data goes

When you run a reasoning loop or the CLI agent, content you provide (your
task, and — depending on the `Context` you build — repository files, diffs,
and documents) is sent to the provider you selected:

- **Model providers** you wire in — for example OpenRouter, Anthropic, OpenAI,
  or Gemini — receive your prompts and the context you include, so they can
  generate a response. Each provider processes that data under **its own**
  terms and privacy policy, which govern whether inputs may be retained or used
  to improve their systems. Essarion does not control those policies.
- **Local models** (e.g. Ollama) run entirely on your machine — in that
  configuration, nothing leaves your computer.
- **Any web, search, or tool integrations you enable** receive only what those
  tools need to run, using your credentials.

You decide what goes into the context. Avoid including secrets or confidential
third-party data you are not permitted to send to your chosen provider.

## Optional telemetry is local-only

The SDK's `configure_telemetry(...)` hook is **off by default**. When enabled,
it invokes a callback **you** supply, in your own process, with plain event
dicts — so you can pipe events into your own logs or observability stack. This
mechanism sends nothing to Essarion.

## Local state on your disk

Session records, budgets, project folders, and applied-change history are
stored locally on your machine (for example under your working directory or
project folders). They are yours to keep or delete. `essarion-build` does not
upload them anywhere.

## Disclaimer

`essarion-build` is provided "as is", without warranty of any kind, as stated
in the Apache License 2.0. It is an **autonomous coding agent**: by default it
can create, edit, and delete files and run commands in a loop. AI-generated
code and commands can be wrong, insecure, or destructive. Review changes and
run agents in an environment you are willing to have modified — for example a
clean git working tree or a container. You are responsible for what you run
and ship.

## Contact

Questions about this note? Email
[hello@essarion.com](mailto:hello@essarion.com).
