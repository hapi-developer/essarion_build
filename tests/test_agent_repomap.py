"""Tests for the repo map / symbol index engine (`agent/_repomap.py`)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from essarion_build.agent import _repomap as rm


def _mkrepo(tmp_path):
    (tmp_path / "lib.py").write_text(
        "def parse(x):\n    return int(x)\n\n"
        "class Widget:\n    def render(self):\n        return parse('1')\n"
    )
    (tmp_path / "app.py").write_text(
        "from lib import parse, Widget\n\n"
        "def main():\n    return parse('2') + Widget().render()\n"
    )
    return tmp_path


def test_build_index_extracts_python_symbols(tmp_path):
    _mkrepo(tmp_path)
    idx = rm.build_index(tmp_path)
    names = {d.name for defs in idx.defs_by_file.values() for d in defs}
    assert {"parse", "Widget", "Widget.render", "main"} <= names
    # signatures are captured
    parse = next(d for defs in idx.defs_by_file.values() for d in defs if d.name == "parse")
    assert parse.signature == "def parse(x)"
    assert parse.kind == "def" and parse.line == 1


def test_render_map_surfaces_widely_referenced_symbol(tmp_path):
    _mkrepo(tmp_path)
    out = rm.render_map(rm.build_index(tmp_path), budget_chars=4000)
    assert "repo map" in out
    # `parse` is referenced from two files → it must make the budgeted map.
    assert "parse" in out
    assert "lib.py" in out and "·L1" in out


def test_render_map_respects_budget(tmp_path):
    _mkrepo(tmp_path)
    tiny = rm.render_map(rm.build_index(tmp_path), budget_chars=600)
    big = rm.render_map(rm.build_index(tmp_path), budget_chars=8000)
    assert len(tiny) <= len(big)
    assert len(tiny) < 1200  # the budget actually bounds output


def test_outline_text_lists_symbols_with_lines(tmp_path):
    _mkrepo(tmp_path)
    out = rm.outline_text(tmp_path, "lib.py")
    assert "class Widget" in out
    assert "def parse(x)" in out
    assert "·L" in out  # line markers present


def test_find_symbol_reports_def_and_refs(tmp_path):
    _mkrepo(tmp_path)
    out = rm.find_symbol_text(tmp_path, "parse")
    assert "1 definition(s)" in out
    assert "lib.py:1" in out
    # referenced from app.py (import + call) and lib.py (render) but NOT counted
    # as the definition line itself.
    assert "app.py:" in out
    assert "lib.py:1:" not in out.split("referenced")[-1]


def test_find_references_is_word_boundary(tmp_path):
    (tmp_path / "m.py").write_text("parser = 1\nparse_all = 2\nparse\n")
    refs = rm.find_references(tmp_path, "parse")
    # `parser` and `parse_all` must NOT match the bare word `parse`.
    assert [ln for _, ln, _ in refs] == [3]


def test_regex_fallback_for_javascript(tmp_path):
    (tmp_path / "a.js").write_text(
        "export class Thing {}\n"
        "function doStuff(a) { return a }\n"
        "const arrow = (x) => x + 1\n"
    )
    idx = rm.build_index(tmp_path)
    names = {d.name for d in idx.defs_by_file["a.js"]}
    assert {"Thing", "doStuff", "arrow"} <= names


def test_pagerank_conserves_mass_and_ranks_central_node():
    edges = {"a": [("b", 1.0)], "c": [("b", 1.0)], "b": [("c", 1.0)]}
    nodes = ["a", "b", "c"]
    rank = rm._pagerank(edges, nodes)
    assert abs(sum(rank.values()) - 1.0) < 1e-6  # mass conserved
    assert rank["b"] > rank["a"]  # b is referenced by two nodes


def test_pagerank_empty():
    assert rm._pagerank({}, []) == {}


def test_personalization_biases_focus(tmp_path):
    _mkrepo(tmp_path)
    idx = rm.build_index(tmp_path)
    scored = rm.rank_symbols(idx, focus={"app.py"})
    top_file = scored[0][1]
    assert top_file == "app.py"  # focus floats its symbols to the top


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_index_respects_gitignore(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("secret.py\ngenerated/\n")
    (tmp_path / "keep.py").write_text("def keep():\n    return 1\n")
    (tmp_path / "secret.py").write_text("def secret():\n    return 2\n")
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "g.py").write_text("def g():\n    return 3\n")
    files = set(rm.build_index(tmp_path).defs_by_file)
    assert "keep.py" in files
    assert "secret.py" not in files          # .gitignore line
    assert "generated/g.py" not in files     # .gitignore dir

