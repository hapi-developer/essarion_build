"""Tests for the PII / secret redaction utilities."""

from __future__ import annotations

import pytest

from essarion_build import Context
from essarion_build._context import Diff, Doc, RepoFile
from essarion_build.redact import (
    in_place,
    list_patterns,
    redact_text,
    register_pattern,
    unregister_pattern,
)


def test_redact_openai_key() -> None:
    text = "OPENAI_API_KEY=sk-AbCdEfGhIjKlMnOpQrSt"
    out, hits = redact_text(text)
    assert "REDACTED:openai_key" in out
    assert "openai_key" in hits


def test_redact_anthropic_key() -> None:
    text = "ANTHROPIC_API_KEY=sk-ant-api03-AbCdEfGhIjKlMnOp"
    out, hits = redact_text(text)
    assert "REDACTED:anthropic_key" in out


def test_redact_github_pat() -> None:
    text = "token = ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    out, hits = redact_text(text)
    assert "REDACTED:github_pat" in out


def test_redact_aws_access_key() -> None:
    text = "AKIAIOSFODNN7EXAMPLE"
    out, hits = redact_text(text)
    assert "REDACTED:aws_access_key" in out


def test_redact_email() -> None:
    out, hits = redact_text("contact alice@example.com about it")
    assert "REDACTED:email" in out
    assert "alice@example.com" not in out


def test_redact_bearer_token() -> None:
    out, _ = redact_text("Authorization: Bearer abc.def.ghi")
    assert "REDACTED:bearer_token" in out


def test_redact_private_key_block() -> None:
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAtX...\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out, _ = redact_text(text)
    assert "REDACTED:private_key_block" in out
    assert "MIIEowIBAAKCAQEAtX" not in out


def test_redact_text_kinds_filter() -> None:
    text = "sk-abcdefghijklmnopqrstuvw and alice@example.com"
    out, hits = redact_text(text, kinds=["openai_key"])
    assert "REDACTED:openai_key" in out
    # email should remain because we restricted kinds
    assert "alice@example.com" in out


def test_in_place_redacts_repo_files() -> None:
    ctx = Context()
    ctx.repo_files.append(
        RepoFile(path="config.py", content="OPENAI = 'sk-abcdefghijklmnopqrstuvw'")
    )
    counts = in_place(ctx)
    assert "REDACTED:openai_key" in ctx.repo_files[0].content
    assert counts["openai_key"] == 1


def test_in_place_redacts_docs() -> None:
    ctx = Context()
    ctx.docs.append(
        Doc(url="https://x.example", body="My PAT: ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    )
    in_place(ctx)
    assert "REDACTED:github_pat" in ctx.docs[0].body


def test_in_place_redacts_diffs_and_notes() -> None:
    ctx = Context()
    ctx.diffs.append(Diff(title="t", body="+ alice@example.com"))
    ctx.notes.append("ping bob@example.com")
    in_place(ctx)
    assert "REDACTED:email" in ctx.diffs[0].body
    assert "REDACTED:email" in ctx.notes[0]


def test_in_place_returns_count_per_kind() -> None:
    ctx = Context()
    ctx.repo_files.append(
        RepoFile(path="a.py", content="alice@example.com and bob@example.com")
    )
    counts = in_place(ctx, kinds=["email"])
    assert counts == {"email": 1}  # one replacement call hit (both emails subbed in one go)


def test_register_custom_pattern() -> None:
    register_pattern("my_internal_token", r"INT-[A-Z0-9]{10}")
    try:
        out, hits = redact_text("look: INT-ABCDEF1234 here", kinds=["my_internal_token"])
        assert "REDACTED:my_internal_token" in out
        assert "my_internal_token" in list_patterns()
    finally:
        unregister_pattern("my_internal_token")


def test_skill_bodies_are_not_redacted() -> None:
    """Bundled skills should never be redacted — they're SDK-shipped content
    and may legitimately contain email-shaped examples."""
    ctx = Context().with_skill("secure_coding")
    # The skill body mentions things like "alg=none" — we don't actively put
    # emails in skills, but if a custom skill did, in_place should leave it.
    original = ctx.builtin_skills[0].body
    in_place(ctx)
    assert ctx.builtin_skills[0].body == original
