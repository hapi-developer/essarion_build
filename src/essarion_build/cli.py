"""essarion-build CLI.

Subcommands:
- `essarion-build skills [--show NAME]`         list bundled skills, or print one
- `essarion-build providers`                    list available providers
- `essarion-build reason "<task>" [...]`        run a reason() loop and print output
- `essarion-build generate "<task>" [...]`      run a generate() loop and print output
- `essarion-build estimate [--repo PATH]`       estimate token cost of a Context
- `essarion-build version`                      print the version

Common flags for `reason` / `generate` / `estimate`:
  --repo PATH          add a repo directory to the context
  --doc URL            add a doc URL to the context (can be repeated)
  --skill NAME         add a bundled skill (repeatable; default: all)
  --no-skills          start with no skills (overrides default)
  --diff FILE          read a diff body from FILE and add it as the focus
  --provider NAME      override provider
  --model NAME         override model
  --max-tokens INT     override per-call max_tokens
  --json               print structured JSON instead of human text
  --stream             stream progress events (reason/generate only)

`reason` / `generate` read additional task text from stdin when the
positional task is `-`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from ._context import Context
from ._generate import generate
from ._providers import list_providers
from ._reasoning import reason
from ._skills import list_skills, load_skill
from ._streaming import ReasoningEvent, stream_generate, stream_reason


def _make_context(args: argparse.Namespace) -> Context:
    ctx = Context()
    if getattr(args, "no_skills", False):
        pass
    elif getattr(args, "skill", None):
        ctx.with_skills(list(args.skill))
    else:
        ctx.with_all_skills()
    if getattr(args, "repo", None):
        ctx.add_repo(args.repo)
    for doc_url in getattr(args, "doc", None) or []:
        ctx.add_docs(doc_url)
    diff_file = getattr(args, "diff", None)
    if diff_file:
        body = Path(diff_file).read_text(encoding="utf-8")
        ctx.add_diff(body, title=Path(diff_file).name)
    return ctx


def _resolve_task(positional: str) -> str:
    if positional == "-":
        return sys.stdin.read().strip()
    return positional


def _common_call_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if getattr(args, "provider", None):
        out["provider"] = args.provider
    if getattr(args, "model", None):
        out["model"] = args.model
    if getattr(args, "max_tokens", None) is not None:
        out["max_tokens"] = args.max_tokens
    return out


def cmd_skills(args: argparse.Namespace) -> int:
    if args.show:
        try:
            print(load_skill(args.show))
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        return 0
    for name in list_skills():
        print(name)
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    for name in list_providers():
        print(name)
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    ctx = _make_context(args)
    chars = ctx.total_chars()
    tokens = ctx.estimate_tokens()
    payload = {
        "chars": chars,
        "estimated_tokens": tokens,
        "skills": len(ctx.builtin_skills) + len(ctx.custom_skills),
        "repo_files": len(ctx.repo_files),
        "docs": len(ctx.docs),
        "diffs": len(ctx.diffs),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Context size: {chars:,} chars ~ {tokens:,} tokens")
        print(f"  skills:    {payload['skills']}")
        print(f"  repo files:{payload['repo_files']}")
        print(f"  docs:      {payload['docs']}")
        print(f"  diffs:     {payload['diffs']}")
    return 0


def _render_reasoning_human(r) -> str:
    out = ["==== plan ====", r.plan, "", "==== tradeoffs ====", r.tradeoffs, "",
           "==== verdict ====", r.verdict, "", f"usage: {r.usage.model_dump()}"]
    return "\n".join(out)


def _render_generation_human(g) -> str:
    out = [
        "==== plan ====", g.reasoning.plan,
        "", "==== tradeoffs ====", g.reasoning.tradeoffs,
        "", "==== code ====", g.code,
        "", "==== defense ====", g.defense,
        "", "==== verdict ====", g.reasoning.verdict,
        "", f"usage: {g.usage.model_dump()}",
    ]
    return "\n".join(out)


def _print_event(ev: ReasoningEvent) -> None:
    if ev.kind == "phase_start":
        print(f"\n>>> {ev.phase} starting <<<", file=sys.stderr, flush=True)
    elif ev.kind == "token":
        sys.stderr.write(ev.text)
        sys.stderr.flush()
    elif ev.kind == "phase_end":
        print(f"\n<<< {ev.phase} done >>>", file=sys.stderr, flush=True)
    elif ev.kind == "usage":
        print(
            f"# usage[{ev.phase}]: {ev.usage.model_dump()}",
            file=sys.stderr,
            flush=True,
        )
    elif ev.kind == "complete":
        print(f"\n# complete: usage={ev.usage.model_dump()}", file=sys.stderr, flush=True)


def cmd_reason(args: argparse.Namespace) -> int:
    task = _resolve_task(args.task)
    ctx = _make_context(args)
    kwargs = _common_call_kwargs(args)
    if args.stream:
        plan_text = ""
        tradeoffs_text = ""
        verdict_text = ""
        for ev in stream_reason(task, context=ctx, **kwargs):
            _print_event(ev)
            if ev.kind == "phase_end":
                plan_text = ev.tags.get("plan", plan_text)
                tradeoffs_text = ev.tags.get("tradeoffs", tradeoffs_text)
                verdict_text = ev.tags.get("verdict", verdict_text)
        if args.json:
            print(json.dumps(
                {"plan": plan_text, "tradeoffs": tradeoffs_text, "verdict": verdict_text}
            ))
        return 0

    result = reason(task, context=ctx, **kwargs)
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(_render_reasoning_human(result))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    task = _resolve_task(args.task)
    ctx = _make_context(args)
    kwargs = _common_call_kwargs(args)
    if args.stream:
        plan_text = tradeoffs_text = verdict_text = code_text = defense_text = ""
        for ev in stream_generate(task, context=ctx, **kwargs):
            _print_event(ev)
            if ev.kind == "phase_end":
                plan_text = ev.tags.get("plan", plan_text)
                tradeoffs_text = ev.tags.get("tradeoffs", tradeoffs_text)
                verdict_text = ev.tags.get("verdict", verdict_text)
                code_text = ev.tags.get("code", code_text)
                defense_text = ev.tags.get("defense", defense_text)
        if args.json:
            print(json.dumps({
                "plan": plan_text, "tradeoffs": tradeoffs_text,
                "verdict": verdict_text, "code": code_text, "defense": defense_text,
            }))
        return 0

    result = generate(task, context=ctx, **kwargs)
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(_render_generation_human(result))
    return 0


def _add_context_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", help="Add a repo directory to the context")
    p.add_argument("--doc", action="append", help="Add a doc URL (repeatable)")
    p.add_argument("--skill", action="append", help="Add a bundled skill (repeatable)")
    p.add_argument("--no-skills", action="store_true", help="Start with no skills")
    p.add_argument("--diff", help="Path to a diff file to focus on")


def _add_call_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", help="Override provider")
    p.add_argument("--model", help="Override model")
    p.add_argument("--max-tokens", type=int, help="Override per-call max_tokens")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of human text")
    p.add_argument("--stream", action="store_true", help="Stream progress events")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="essarion-build",
        description="BYOK reasoning amplification SDK CLI.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_skills = sub.add_parser("skills", help="List or print bundled skills")
    p_skills.add_argument("--show", help="Print the body of NAME")
    p_skills.set_defaults(func=cmd_skills)

    p_providers = sub.add_parser("providers", help="List available providers")
    p_providers.set_defaults(func=cmd_providers)

    p_version = sub.add_parser("version", help="Print the SDK version")
    p_version.set_defaults(func=cmd_version)

    p_estimate = sub.add_parser(
        "estimate", help="Estimate token cost of a Context"
    )
    _add_context_flags(p_estimate)
    p_estimate.add_argument("--json", action="store_true")
    p_estimate.set_defaults(func=cmd_estimate)

    p_reason = sub.add_parser("reason", help="Run a reason() loop")
    p_reason.add_argument("task", help="Task description (or '-' for stdin)")
    _add_context_flags(p_reason)
    _add_call_flags(p_reason)
    p_reason.set_defaults(func=cmd_reason)

    p_generate = sub.add_parser("generate", help="Run a generate() loop")
    p_generate.add_argument("task", help="Task description (or '-' for stdin)")
    _add_context_flags(p_generate)
    _add_call_flags(p_generate)
    p_generate.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 - top-level CLI surface
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
