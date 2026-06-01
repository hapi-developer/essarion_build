"""Tests for the agent's sandboxed tool surface."""

from __future__ import annotations

import pytest

from essarion_build.agent import _tools


def test_apply_diff_fuzzy_trailing_whitespace(tmp_path) -> None:
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    _tools.bind_tools(tmp_path)
    # `old` carries trailing whitespace the file lacks → exact miss, fuzzy hit.
    _tools.apply_diff("a.py", "    return 1   ", "    return 2")
    assert (tmp_path / "a.py").read_text() == "def f():\n    return 2\n"


def test_apply_diff_fuzzy_reindents_to_match(tmp_path) -> None:
    (tmp_path / "c.py").write_text("class C:\n        def m(self):\n            pass\n")
    _tools.bind_tools(tmp_path)
    # Snippet has no leading indent; the fuzzy match re-indents `new` to align.
    _tools.apply_diff("c.py", "def m(self):\n    pass", "def m(self):\n    return 42")
    assert (tmp_path / "c.py").read_text() == "class C:\n        def m(self):\n            return 42\n"


def test_apply_diff_still_refuses_truly_absent(tmp_path) -> None:
    (tmp_path / "d.py").write_text("alpha\nbeta\n")
    _tools.bind_tools(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        _tools.apply_diff("d.py", "gamma\ndelta", "x")


def test_read_file_within_sandbox(tmp_path) -> None:
    (tmp_path / "a.py").write_text("print(1)\n")
    _tools.bind_tools(tmp_path)
    assert _tools.read_file("a.py").strip() == "print(1)"


def test_read_file_traversal_blocked(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    with pytest.raises(PermissionError):
        _tools.read_file("../../etc/passwd")


def test_list_dir_skips_hidden(tmp_path) -> None:
    (tmp_path / "visible.py").write_text("x")
    (tmp_path / ".secret").write_text("s")
    _tools.bind_tools(tmp_path)
    out = _tools.list_dir(".")
    assert "visible.py" in out
    assert ".secret" not in out


def test_list_dir_keeps_gitignore_exception(tmp_path) -> None:
    (tmp_path / ".gitignore").write_text("*.tmp")
    _tools.bind_tools(tmp_path)
    out = _tools.list_dir(".")
    assert ".gitignore" in out


def test_grep_finds_matches(tmp_path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    (tmp_path / "b.py").write_text("def bar():\n    return foo()\n")
    _tools.bind_tools(tmp_path)
    out = _tools.grep(r"foo")
    assert "a.py:1" in out
    assert "b.py:2" in out


def test_grep_skips_vcs_dirs(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("foo")
    (tmp_path / "a.py").write_text("foo")
    _tools.bind_tools(tmp_path)
    out = _tools.grep(r"foo")
    assert "a.py" in out
    assert ".git" not in out


def test_write_file_creates_parent_dirs(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    _tools.write_file("sub/dir/new.py", "x = 1\n")
    assert (tmp_path / "sub" / "dir" / "new.py").read_text() == "x = 1\n"


def test_apply_diff_unique_occurrence(tmp_path) -> None:
    (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
    _tools.bind_tools(tmp_path)
    _tools.apply_diff("f.py", "b = 2", "b = 99")
    assert (tmp_path / "f.py").read_text() == "a = 1\nb = 99\n"


def test_apply_diff_refuses_missing(tmp_path) -> None:
    (tmp_path / "f.py").write_text("a = 1\n")
    _tools.bind_tools(tmp_path)
    with pytest.raises(ValueError):
        _tools.apply_diff("f.py", "missing", "x")


def test_apply_diff_refuses_ambiguous(tmp_path) -> None:
    (tmp_path / "f.py").write_text("x\nx\n")
    _tools.bind_tools(tmp_path)
    with pytest.raises(ValueError):
        _tools.apply_diff("f.py", "x", "y")


def test_run_shell_captures_output(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    out = _tools.run_shell("echo hello")
    assert "hello" in out
    assert "[exit 0]" in out


def test_run_shell_timeout(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    out = _tools.run_shell("sleep 5", timeout=1)
    assert "timed out" in out


def test_run_shell_supports_shell_operators(tmp_path) -> None:
    """Redirection, pipes, and && must work — models write them constantly."""
    _tools.bind_tools(tmp_path)
    _tools.run_shell("echo 'hello world' > greeting.txt")
    assert (tmp_path / "greeting.txt").read_text().strip() == "hello world"
    # pipe + &&
    out = _tools.run_shell("printf 'a\\nb\\nc\\n' | wc -l && echo done")
    assert "3" in out and "done" in out
    assert "[exit 0]" in out


def test_register_all_wires_sdk_tools() -> None:
    """All built-in agent tools are registered with the SDK's tool surface."""
    from essarion_build import tools as sdk_tools

    _tools.register_all()
    names = {t.name for t in sdk_tools.list_tools()}
    for required in {"read_file", "list_dir", "grep", "write_file", "apply_diff", "run_shell"}:
        assert required in names


# ---------- code-intelligence tools ----------

def test_outline_tool_lists_symbols(tmp_path) -> None:
    (tmp_path / "m.py").write_text("def a():\n    pass\n\nclass C:\n    def x(self):\n        pass\n")
    _tools.bind_tools(tmp_path)
    out = _tools.outline("m.py")
    assert "def a()" in out and "class C" in out and "def x(self)" in out


def test_find_symbol_tool_reports_def_and_refs(tmp_path) -> None:
    (tmp_path / "m.py").write_text("def a():\n    return 1\n\ndef b():\n    return a()\n")
    _tools.bind_tools(tmp_path)
    out = _tools.find_symbol("a")
    assert "definition" in out and "m.py:1" in out
    assert "m.py:5" in out  # the call site in b()


def test_repo_map_tool_renders(tmp_path) -> None:
    (tmp_path / "m.py").write_text("def alpha():\n    return 1\n")
    _tools.bind_tools(tmp_path)
    out = _tools.repo_map()
    assert "repo map" in out and "m.py" in out


def test_edit_symbol_rewrites_function(tmp_path) -> None:
    (tmp_path / "m.py").write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    _tools.bind_tools(tmp_path)
    _tools.edit_symbol("m.py", "a", "def a():\n    return 99")
    txt = (tmp_path / "m.py").read_text()
    assert "return 99" in txt and "def b():" in txt and "return 2" in txt


def test_edit_symbol_dotted_method(tmp_path) -> None:
    (tmp_path / "m.py").write_text("class C:\n    def m(self):\n        return 1\n")
    _tools.bind_tools(tmp_path)
    _tools.edit_symbol("m.py", "C.m", "def m(self):\n    return 2")
    txt = (tmp_path / "m.py").read_text()
    assert "return 2" in txt and "class C:" in txt


def test_edit_symbol_not_found_raises(tmp_path) -> None:
    (tmp_path / "m.py").write_text("def a():\n    return 1\n")
    _tools.bind_tools(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        _tools.edit_symbol("m.py", "zzz", "def zzz():\n    pass")


def test_edit_symbol_refuses_unparseable_result(tmp_path) -> None:
    (tmp_path / "m.py").write_text("def a():\n    return 1\n")
    _tools.bind_tools(tmp_path)
    with pytest.raises(ValueError, match="not parse"):
        _tools.edit_symbol("m.py", "a", "def a(:\n  broken")
    assert "return 1" in (tmp_path / "m.py").read_text()  # left unchanged


def test_edit_symbol_rejects_non_python(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    _tools.bind_tools(tmp_path)
    with pytest.raises(ValueError, match="Python"):
        _tools.edit_symbol("a.txt", "x", "y")


# ---------- post-edit feedback ----------

def test_write_file_flags_syntax_error(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    out = _tools.write_file("bad.py", "def f(:\n    pass\n")
    assert "⚠" in out and "syntax error" in out


def test_write_file_clean_has_no_warning(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    out = _tools.write_file("ok.py", "def f():\n    return 1\n")
    assert "⚠" not in out


def test_write_file_flags_bad_json(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    out = _tools.write_file("d.json", "{not valid")
    assert "⚠" in out and "JSON" in out


def test_apply_diff_blast_radius_note(tmp_path) -> None:
    (tmp_path / "lib.py").write_text("def helper(x):\n    return x\n")
    (tmp_path / "use.py").write_text("from lib import helper\nhelper(1)\n")
    _tools.bind_tools(tmp_path)
    out = _tools.apply_diff("lib.py", "def helper(x):\n    return x", "def helper2(x):\n    return x")
    assert "↔" in out and "helper" in out and "use.py" in out


# ---------- web_fetch ----------

class _FakeResp:
    def __init__(self, body: bytes, ctype: str = "text/html") -> None:
        self._b = body
        self.headers = {"Content-Type": ctype}
    def read(self, n: int = -1) -> bytes:
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_web_fetch_strips_html(monkeypatch) -> None:
    import urllib.request
    body = b"<html><body><h1>Title</h1><script>alert(1)</script><p>Paragraph</p></body></html>"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp(body))
    out = _tools.web_fetch("http://example.test")
    assert "Title" in out and "Paragraph" in out
    assert "alert" not in out  # script content dropped


def test_web_fetch_network_error_is_graceful(monkeypatch) -> None:
    import urllib.error
    import urllib.request

    def _boom(*a, **k):
        raise urllib.error.URLError("blocked")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    out = _tools.web_fetch("http://example.test")
    assert out.startswith("(could not fetch")
