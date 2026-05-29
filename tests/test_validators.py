"""Tests for the validators module."""

from __future__ import annotations

import pytest

from essarion_build.validators import (
    Issue,
    list_validators,
    register_validator,
    validate,
    validate_json,
    validate_python,
    validate_unified_diff,
)


def test_python_valid_returns_empty() -> None:
    assert validate_python("def f(x):\n    return x + 1\n") == []


def test_python_syntax_error_returns_error_issue() -> None:
    issues = validate_python("def f(:\n    pass")
    assert any(i.kind == "syntax" and i.severity == "error" for i in issues)


def test_python_bare_except_flagged() -> None:
    code = "try:\n    x = 1\nexcept:\n    pass\n"
    issues = validate_python(code)
    assert any(i.kind == "bare_except" for i in issues)


def test_python_eval_flagged_as_error() -> None:
    code = "x = eval('1+1')\n"
    issues = validate_python(code)
    assert any(i.kind == "dangerous_call" and i.severity == "error" for i in issues)


def test_python_mutable_default_flagged() -> None:
    code = "def f(x=[]):\n    return x\n"
    issues = validate_python(code)
    assert any(i.kind == "mutable_default" for i in issues)


def test_python_todo_marker_info_only() -> None:
    code = "# TODO: implement\ndef f():\n    return 1\n"
    issues = validate_python(code)
    assert any(i.kind == "open_marker" and i.severity == "info" for i in issues)


def test_python_clean_modern_code_has_no_issues() -> None:
    code = (
        "from typing import Sequence\n"
        "def sum_squares(nums: Sequence[int]) -> int:\n"
        "    return sum(x * x for x in nums)\n"
    )
    assert validate_python(code) == []


def test_json_valid() -> None:
    assert validate_json('{"a": 1, "b": [2, 3]}') == []


def test_json_invalid_returns_error() -> None:
    issues = validate_json('{"a": 1,}')  # trailing comma — not valid JSON
    assert issues
    assert issues[0].severity == "error"


def test_diff_with_headers_passes() -> None:
    diff = (
        "--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    )
    assert validate_unified_diff(diff) == []


def test_diff_without_headers_flags_not_a_diff() -> None:
    issues = validate_unified_diff("print('hello')\n")
    assert issues
    assert issues[0].kind == "not_a_diff"


def test_validate_dispatcher() -> None:
    assert validate("def f(): pass", kind="python") == []
    assert validate("{", kind="json") != []
    assert validate("print(1)", kind="diff") != []


def test_validate_unknown_kind_returns_empty() -> None:
    assert validate("anything", kind="cobol") == []


def test_register_custom_validator() -> None:
    def my_validator(code: str) -> list[Issue]:
        if "BANNED" in code:
            return [Issue(kind="banned", message="don't use BANNED", severity="error")]
        return []

    register_validator("custom-lang", my_validator)
    try:
        assert validate("ok", kind="custom-lang") == []
        issues = validate("hello BANNED", kind="custom-lang")
        assert issues and issues[0].kind == "banned"
        assert "custom-lang" in list_validators()
    finally:
        from essarion_build.validators import _VALIDATORS

        _VALIDATORS.pop("custom-lang", None)
