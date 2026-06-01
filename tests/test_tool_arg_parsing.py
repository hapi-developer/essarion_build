"""Robust tool-call arg parsing — regression tests for what REAL models emit.

The deterministic agent tests build args with json.dumps(), so they never hit
the messy shapes a live model produces: multi-line file content (literal
newlines in JSON strings), markdown-fenced JSON, and natural-language arg names
like run_shell "command". A live OpenRouter run surfaced all of these; these
tests lock in the fixes without needing the network."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build import tools as sdk_tools
from essarion_build.agent._tools import bind_tools, register_all


@pytest.fixture(autouse=True)
def _sandbox(tmp_path: Path):
    bind_tools(tmp_path)
    register_all()
    return tmp_path


def test_multiline_file_content_parses_and_writes(_sandbox) -> None:
    # A real model emits the file body with LITERAL newlines inside the JSON
    # string — invalid under strict JSON, fine with strict=False.
    body = "import re\n\ndef slug(s):\n    return s.lower()\n"
    call = f'<tool_call name="write_file">{{"path": "slug.py", "content": "{body}"}}</tool_call>'
    out = sdk_tools.run_tools_in_plan(call, allow={"write_file"})
    assert "error=" not in out, out
    written = (_sandbox / "slug.py").read_text()
    assert "def slug(s):" in written and written == body


def test_xml_child_tag_args_write_multiline_file(_sandbox) -> None:
    # Claude-family models emit multi-line file bodies as <path>/<content> tags
    # rather than JSON. This is the exact shape a live OpenRouter run produced.
    call = (
        '<tool_call name="write_file">\n'
        "<path>slugify.py</path>\n"
        "<content>import re\n\n"
        "def slugify(text):\n"
        "    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')\n"
        "</content>\n"
        "</tool_call>"
    )
    out = sdk_tools.run_tools_in_plan(call, allow={"write_file"})
    assert "error=" not in out, out
    written = (_sandbox / "slugify.py").read_text()
    assert written.startswith("import re")
    assert "def slugify(text):" in written


def test_xml_child_tag_nested_tags_absorbed(_sandbox) -> None:
    # Tags *inside* a value (e.g. HTML) must not become spurious extra args.
    call = (
        '<tool_call name="write_file">'
        "<path>page.html</path>"
        "<content><div>hi</div></content>"
        "</tool_call>"
    )
    out = sdk_tools.run_tools_in_plan(call, allow={"write_file"})
    assert "error=" not in out, out
    assert (_sandbox / "page.html").read_text() == "<div>hi</div>"


def test_markdown_fenced_args_parse(_sandbox) -> None:
    call = (
        '<tool_call name="write_file">```json\n'
        '{"path": "a.txt", "content": "hi"}\n'
        "```</tool_call>"
    )
    out = sdk_tools.run_tools_in_plan(call, allow={"write_file"})
    assert "error=" not in out, out
    assert (_sandbox / "a.txt").read_text() == "hi"


def test_run_shell_command_alias(_sandbox) -> None:
    # Model says "command"; the tool's param is "cmd". Must still run.
    call = '<tool_call name="run_shell">{"command": "echo hello-alias"}</tool_call>'
    out = sdk_tools.run_tools_in_plan(call, allow={"run_shell"})
    assert "error=" not in out, out
    assert "hello-alias" in out


def test_coerce_tool_args_direct() -> None:
    assert sdk_tools.coerce_tool_args('{"a": 1}') == {"a": 1}
    assert sdk_tools.coerce_tool_args("") == {}
    # literal newline inside a string value
    assert sdk_tools.coerce_tool_args('{"content": "a\nb"}') == {"content": "a\nb"}
    with pytest.raises((ValueError, Exception)):
        sdk_tools.coerce_tool_args("[1, 2, 3]")  # not an object


def test_manifest_exposes_exact_parameter_names(_sandbox) -> None:
    manifest = sdk_tools.tool_manifest()
    # The model can now SEE the real names instead of guessing.
    assert "run_shell(cmd" in manifest
    assert "write_file(path, content)" in manifest
    assert "read_file(path" in manifest
