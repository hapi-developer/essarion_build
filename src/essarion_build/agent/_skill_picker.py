"""Smart skill selection — one of the agent's edges.

Loading all 54 bundled skills on every task wastes thousands of input
tokens. Picking 0–3 by hand is what most users would do; we want to be
better than that without being slower.

Strategy:

1. **Keyword pre-filter.** Each skill's name + first-line tagline forms
   a tiny corpus. For the user's task, count keyword overlap against
   each skill's corpus. Cheap, deterministic, no model call.
2. **Top-K pick.** Take the N highest-scoring skills (default 5). Always
   include `scope_discipline` and `error_handling` because they apply
   to literally every coding task.
3. **Optional model-driven refinement.** If `mode="model"`, the picker
   makes one ~200-token call to the cheap model to refine the choice.
   Off by default; the keyword heuristic is good enough for most tasks
   and free.

The output is a list of skill names ready for `Context.with_skills(...)`.
"""

from __future__ import annotations

import re
from collections import Counter

from .._skills import list_skills, load_skill


# Skills that essentially apply to every coding task. We always include
# them so the model gets the "stay in scope" + "don't swallow exceptions"
# nudges even when the keyword score doesn't surface them.
_ALWAYS_INCLUDE = ["scope_discipline", "error_handling"]

# Common English stop-words. Tiny list — we don't need linguistic depth.
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "i", "if", "in", "into", "is", "it", "its", "let", "make",
    "of", "on", "or", "so", "such", "that", "the", "their", "then", "there",
    "these", "they", "this", "to", "us", "was", "we", "what", "when", "which",
    "who", "will", "with", "you", "your", "do", "does", "did", "can", "could",
    "should", "would", "want", "wants", "wanted", "been", "being", "i'd",
    "i'm", "i've", "im", "ill",
}


def _tokenize(s: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z_]+", s.lower()) if w not in _STOP and len(w) > 2]


# Lightweight corpus per skill: name + first 2-3 bullets.  Cached on first
# build so we don't re-read the markdown for every picker call.
_SKILL_CORPUS_CACHE: dict[str, set[str]] = {}


def _skill_corpus(name: str) -> set[str]:
    """The tokens that count toward a skill's relevance score."""
    if name in _SKILL_CORPUS_CACHE:
        return _SKILL_CORPUS_CACHE[name]
    body = load_skill(name)
    # Take the H1 line + the first ~10 bullet-line opening words. Enough
    # signal to match against keywords, not so much that everything matches.
    keep_lines: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("-") or line.startswith("*"):
            keep_lines.append(line)
        if len(keep_lines) >= 12:
            break
    tokens = set(_tokenize(" ".join(keep_lines)))
    # Also fold the skill name itself in (split by underscore).
    for piece in name.split("_"):
        if len(piece) > 2:
            tokens.add(piece.lower())
    _SKILL_CORPUS_CACHE[name] = tokens
    return tokens


def pick_skills(
    task: str,
    *,
    top_k: int = 5,
    available: list[str] | None = None,
    always_include: list[str] | None = None,
) -> list[str]:
    """Pick the `top_k` most-relevant skills for `task` from `available`.

    Returns the picks in score order. `_ALWAYS_INCLUDE` skills are added
    at the end if they weren't already in the top-K (so they take a slot
    *above* `top_k`, not inside).
    """
    pool = available if available is not None else list_skills()
    always = always_include if always_include is not None else _ALWAYS_INCLUDE
    task_tokens = Counter(_tokenize(task))
    if not task_tokens:
        # Empty task → fall back to the always-include set only.
        return list(dict.fromkeys(always))

    scored: list[tuple[int, str]] = []
    for name in pool:
        corpus = _skill_corpus(name)
        if not corpus:
            scored.append((0, name))
            continue
        score = sum(count for tok, count in task_tokens.items() if tok in corpus)
        # Tiny bonus if the skill name itself appears in the task.
        for piece in name.split("_"):
            if piece and piece in task_tokens:
                score += 3
        scored.append((score, name))

    scored.sort(key=lambda t: (-t[0], t[1]))
    picks = [name for score, name in scored[:top_k] if score > 0]

    for n in always:
        if n in pool and n not in picks:
            picks.append(n)
    return picks


def explain_pick(task: str, picks: list[str]) -> str:
    """A one-line human-readable reason the picker chose what it chose.

    Just lists matching tokens per skill. Useful for the UI's footer or
    a `/skills` slash command.
    """
    task_tokens = set(_tokenize(task))
    out: list[str] = []
    for name in picks:
        corpus = _skill_corpus(name)
        hits = sorted(task_tokens & corpus)[:3]
        if hits:
            out.append(f"{name} ({', '.join(hits)})")
        else:
            out.append(name)
    return "; ".join(out)
