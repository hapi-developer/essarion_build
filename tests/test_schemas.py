"""Tests for the JSON-schema mode (generate_json)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from essarion_build import Context, LiteRuntime, StubProvider
from essarion_build._schemas import (
    SchemaValidationError,
    _try_parse,
    generate_json,
)


class Person(BaseModel):
    name: str
    age: int


def test_try_parse_pydantic_success() -> None:
    parsed, err = _try_parse('{"name": "alice", "age": 30}', Person)
    assert err is None
    assert parsed == {"name": "alice", "age": 30}


def test_try_parse_pydantic_validation_error() -> None:
    _, err = _try_parse('{"name": "alice", "age": "thirty"}', Person)
    assert err is not None
    assert "pydantic" in err


def test_try_parse_invalid_json() -> None:
    _, err = _try_parse("{not json", Person)
    assert err is not None
    assert "not valid JSON" in err


def test_try_parse_raw_schema_missing_required() -> None:
    schema = {"type": "object", "required": ["name", "age"]}
    _, err = _try_parse('{"name": "alice"}', schema)
    assert err is not None
    assert "age" in err


def test_try_parse_raw_schema_top_level_not_object() -> None:
    schema = {"type": "object"}
    _, err = _try_parse("[1, 2]", schema)
    assert err is not None
    assert "must be a JSON object" in err


def test_generate_json_happy_path_with_pydantic() -> None:
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            '<code>{"name": "Alice", "age": 30}</code>',
            "<verdict>ship</verdict><defense>safe</defense>",
        ]
    )
    parsed, gen = generate_json(
        "describe a person",
        schema=Person,
        context=Context(),
        _runtime=LiteRuntime(stub),
    )
    assert parsed == {"name": "Alice", "age": 30}
    assert gen.code == '{"name": "Alice", "age": 30}'


def test_generate_json_repair_pass_when_first_invalid() -> None:
    stub = StubProvider(
        responses=[
            # First generate() loop: invalid JSON.
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            '<code>{"name": "Alice"}</code>',  # missing age
            "<verdict>ship</verdict><defense>ok</defense>",
            # Second generate() loop after repair: valid.
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            '<code>{"name": "Alice", "age": 30}</code>',
            "<verdict>ship</verdict><defense>ok</defense>",
        ]
    )
    parsed, gen = generate_json(
        "describe a person",
        schema=Person,
        context=Context(),
        _runtime=LiteRuntime(stub),
    )
    assert parsed["age"] == 30
    # Usage aggregated across both passes.
    assert stub.call_count == 6


def test_generate_json_raises_when_repair_fails() -> None:
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            '<code>not json at all</code>',
            "<verdict>ship</verdict><defense>ok</defense>",
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            '<code>still not json</code>',
            "<verdict>ship</verdict><defense>ok</defense>",
        ]
    )
    with pytest.raises(SchemaValidationError):
        generate_json(
            "describe a person",
            schema=Person,
            context=Context(),
            _runtime=LiteRuntime(stub),
        )


def test_generate_json_with_raw_dict_schema() -> None:
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            '<code>{"title": "T", "items": ["a"]}</code>',
            "<verdict>ship</verdict><defense>ok</defense>",
        ]
    )
    schema = {"type": "object", "required": ["title", "items"]}
    parsed, _ = generate_json(
        "make a list",
        schema=schema,
        context=Context(),
        _runtime=LiteRuntime(stub),
    )
    assert parsed["title"] == "T"
