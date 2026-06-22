"""essarion-build CLI.

Subcommands:
- `essarion-build skills [--show NAME]`         list bundled skills, or print one
- `essarion-build providers`                    list available providers
- `essarion-build reason "<task>" [...]`        run a reason() loop and print output
- `essarion-build generate "<task>" [...]`      run a generate() loop and print output
- `essarion-build review [--diff F] [...]`      review a diff (+ cross-model 2nd opinion) for CI
- `essarion-build schedule <action> [...]`      manage / run recurring tasks (cron-style)
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


_REVIEW_SKILLS = [
    "code_review", "secure_coding", "error_handling",
    "concurrency", "testing", "scope_discipline",
]
_REVIEW_GOAL = (
    "Review this change for correctness, security, and edge-case bugs. "
    "Cite file:line for each finding and end with whether it is safe to ship."
)


def _resolve_review_diff(args: argparse.Namespace) -> str:
    """The diff to review: an explicit --diff file (or '-' for stdin), else
    `git diff [<base>...HEAD]` in the repo."""
    import subprocess

    if getattr(args, "diff", None):
        if args.diff == "-":
            return sys.stdin.read()
        return Path(args.diff).read_text(encoding="utf-8")
    repo = getattr(args, "repo", None) or "."
    cmd = ["git", "-C", repo, "diff"]
    if getattr(args, "base", None):
        cmd.append(f"{args.base}...HEAD")
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _render_review_markdown(r, opinion) -> str:
    """Render a review (+ optional cross-model second opinion) as PR-ready
    markdown."""
    lines = [
        "## 🔎 essarion-build review",
        "",
        f"**Verdict:** {(r.verdict or '—').strip()}",
        "",
        "### Findings",
        (r.plan or "_no findings_").strip(),
    ]
    if opinion is not None:
        lines += ["", f"### Cross-model second opinion — `{opinion.model}`"]
        if not opinion.ok:
            lines.append(f"_independent review call failed: {opinion.error}_")
        else:
            stance = (
                "agree — safe to ship"
                if opinion.agree and not opinion.concerns
                else "concerns raised"
            )
            lines.append(f"**Independent stance:** {stance}")
            if opinion.concerns:
                lines.append("")
                lines += [f"- {c}" for c in opinion.concerns]
            if opinion.summary:
                lines += ["", f"> {opinion.summary.strip()}"]
        lines += [
            "",
            "_Two different models reviewed this change independently — "
            "where they disagree is where bugs hide._",
        ]
    total = getattr(getattr(r, "usage", None), "total_tokens", 0)
    lines += ["", f"<sub>essarion-build · {total:,} tokens</sub>"]
    return "\n".join(lines)


def cmd_review(args: argparse.Namespace) -> int:
    """Review a diff with the plan→selfcheck loop, plus an optional INDEPENDENT
    cross-model second opinion — the CI surface for essarion's crosscheck."""
    from ._config import current
    from ._providers import build_provider
    from .agent._crosscheck import request_second_opinion

    diff = _resolve_review_diff(args)
    if not diff.strip():
        print("(no diff to review)")
        return 0

    ctx = Context()
    if getattr(args, "no_skills", False):
        pass
    elif getattr(args, "skill", None):
        ctx.with_skills(list(args.skill))
    else:
        ctx.with_skills(_REVIEW_SKILLS)
    if getattr(args, "repo", None):
        ctx.add_repo(args.repo)
    ctx.add_diff(diff, title=getattr(args, "base", None) or "review")

    goal = getattr(args, "goal", None) or _REVIEW_GOAL
    kwargs = _common_call_kwargs(args)
    r = reason(goal, context=ctx, **kwargs)

    opinion = None
    if getattr(args, "crosscheck_model", None):
        prov_name = getattr(args, "provider", None) or current().provider
        try:
            prov = build_provider(
                name=prov_name, api_key=None, model=args.crosscheck_model
            )
            opinion = request_second_opinion(
                prov, goal=goal, change=diff, model=args.crosscheck_model
            )
        except Exception as e:  # noqa: BLE001 - a failed 2nd opinion never blocks
            print(f"# crosscheck unavailable: {e}", file=sys.stderr)

    if args.json:
        payload: dict[str, Any] = {
            "verdict": r.verdict,
            "findings": r.plan,
            "tradeoffs": r.tradeoffs,
            "usage": r.usage.model_dump(),
        }
        if opinion is not None:
            payload["crosscheck"] = {
                "model": opinion.model,
                "agree": opinion.agree,
                "disagrees": opinion.disagrees,
                "concerns": opinion.concerns,
                "summary": opinion.summary,
                "ok": opinion.ok,
                "error": opinion.error,
            }
        print(json.dumps(payload, indent=2))
    else:
        print(_render_review_markdown(r, opinion))

    if getattr(args, "fail_on_disagree", False) and opinion is not None and opinion.disagrees:
        return 3
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    """Manage and run recurring tasks (the cron-style automation surface)."""
    import os
    import time

    from .agent._schedule import (
        format_interval,
        load_schedule,
        run_due,
        run_one,
    )

    cwd = getattr(args, "cwd", None) or os.getcwd()
    action = args.action
    sched = load_schedule(cwd)

    if action == "list":
        if not sched.jobs:
            print("(no scheduled jobs)")
            print(f"file: {sched.path}")
            return 0
        for j in sched.jobs:
            when = (
                time.strftime("%Y-%m-%d %H:%M", time.localtime(j.next_run))
                if j.next_run
                else "?"
            )
            state = "on " if j.enabled else "OFF"
            label = f"  ·  {j.name}" if j.name else ""
            print(
                f"{j.id}  every {format_interval(j.every):>4}  [{state}]  "
                f"next {when}  runs={j.runs}{label}"
            )
            print(f"        {j.task}")
        return 0

    if action == "add":
        if not args.target or not args.every:
            print('usage: essarion schedule add "<task>" --every 1d', file=sys.stderr)
            return 2
        try:
            job = sched.add(
                args.target,
                args.every,
                name=args.name or "",
                model=args.model,
                budget=args.budget,
                due_now=args.now,
            )
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        sched.save()
        print(f"added {job.id}: every {format_interval(job.every)} · {job.task}")
        return 0

    if action == "rm":
        if not args.target:
            print("usage: essarion schedule rm <id>", file=sys.stderr)
            return 2
        ok = sched.remove(args.target)
        sched.save()
        print(f"removed {args.target}" if ok else f"no job {args.target}")
        return 0 if ok else 1

    if action in ("enable", "disable"):
        if not args.target:
            print(f"usage: essarion schedule {action} <id>", file=sys.stderr)
            return 2
        ok = sched.set_enabled(args.target, action == "enable")
        sched.save()
        print(f"{action}d {args.target}" if ok else f"no job {args.target}")
        return 0 if ok else 1

    if action == "run":
        if not args.target:
            print("usage: essarion schedule run <id>", file=sys.stderr)
            return 2
        try:
            status = run_one(cwd, args.target)
        except KeyError:
            print(f"no job {args.target}", file=sys.stderr)
            return 1
        print(f"{args.target}: {status}")
        return 0

    if action == "run-due":
        if args.loop:
            interval = max(5, int(args.loop))
            print(
                f"scheduler loop: re-checking every {interval}s (Ctrl-C to stop)",
                file=sys.stderr,
            )
            while True:
                for job, status in run_due(cwd):
                    print(f"{time.strftime('%H:%M:%S')} ran {job.id}: {status}")
                time.sleep(interval)
        ran = run_due(cwd)
        if not ran:
            print("(nothing due)")
        for job, status in ran:
            print(f"ran {job.id}: {status}")
        return 0

    print(f"unknown action {action!r}", file=sys.stderr)
    return 2


def cmd_workflows(args: argparse.Namespace) -> int:
    """Print the list of bundled workflows."""
    from . import workflows as wf

    for name in wf.__all__:
        fn = getattr(wf, name)
        doc = (fn.__doc__ or "").strip().split("\n", 1)[0]
        print(f"{name:24s} {doc}")
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

    p_workflows = sub.add_parser("workflows", help="List bundled workflows")
    p_workflows.set_defaults(func=cmd_workflows)

    p_review = sub.add_parser(
        "review",
        help="Review a diff (+ optional cross-model second opinion) — the CI surface",
    )
    p_review.add_argument("--diff", help="Diff file to review ('-' for stdin)")
    p_review.add_argument(
        "--base", help="Git base ref; reviews `git diff <base>...HEAD` (CI/PRs)"
    )
    p_review.add_argument("--goal", help="What the change is meant to accomplish")
    p_review.add_argument("--repo", help="Repo dir for context + git (default: .)")
    p_review.add_argument("--skill", action="append", help="Override review skills (repeatable)")
    p_review.add_argument("--no-skills", action="store_true", help="Review with no skills")
    p_review.add_argument(
        "--crosscheck-model",
        help="A DIFFERENT model that independently red-teams the change",
    )
    p_review.add_argument(
        "--fail-on-disagree",
        action="store_true",
        help="Exit 3 if the cross-model reviewer disagrees (gate CI on it)",
    )
    p_review.add_argument("--provider", help="Override provider")
    p_review.add_argument("--model", help="Override model")
    p_review.add_argument("--max-tokens", type=int, help="Override per-call max_tokens")
    p_review.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    p_review.set_defaults(func=cmd_review)

    p_sched = sub.add_parser(
        "schedule", help="Manage recurring tasks (cron-style automation)"
    )
    p_sched.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "add", "rm", "run", "run-due", "enable", "disable"],
        help="what to do (default: list)",
    )
    p_sched.add_argument(
        "target", nargs="?", help="task text (add) or job id (rm/run/enable/disable)"
    )
    p_sched.add_argument("--every", help="interval: 30s / 10m / 2h / 1d / 1w")
    p_sched.add_argument("--name", help="label for the job")
    p_sched.add_argument("--model", help="model override for this job")
    p_sched.add_argument("--budget", type=float, help="USD budget for this job")
    p_sched.add_argument(
        "--now", action="store_true", help="(add) make the job due immediately"
    )
    p_sched.add_argument(
        "--loop",
        type=int,
        metavar="SECONDS",
        help="(run-due) keep running, re-checking every SECONDS",
    )
    p_sched.add_argument("--cwd", help="project dir (default: current dir)")
    p_sched.set_defaults(func=cmd_schedule)

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
