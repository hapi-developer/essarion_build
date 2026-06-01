"""The multimodal seam: neutral content blocks render to each provider's shape,
the autonomous loop attaches screenshots only on vision models, and the
OpenAI/OpenRouter body carries images. No network."""

from __future__ import annotations

from essarion_build._content import (
    content_to_text,
    has_images,
    image_block,
    render_anthropic,
    render_gemini_parts,
    render_openai,
    text_block,
)


def test_string_content_passes_through_unchanged() -> None:
    assert render_openai("hello") == "hello"
    assert render_anthropic("hi") == "hi"
    assert render_gemini_parts("yo") == [{"text": "yo"}]
    assert content_to_text("plain") == "plain"


def test_image_block_from_bytes_is_base64() -> None:
    b = image_block(b"\x89PNG\r\n", "image/png")
    assert b["type"] == "image" and b["media_type"] == "image/png"
    assert b["data"] == "iVBORw0K"  # base64 of those bytes
    # passing an already-encoded string is left alone
    assert image_block("YWJj", "image/png")["data"] == "YWJj"


def test_render_openai_multimodal() -> None:
    content = [text_block("what is this?"), image_block(b"xy", "image/png")]
    out = render_openai(content)
    assert out[0] == {"type": "text", "text": "what is this?"}
    assert out[1]["type"] == "image_url"
    assert out[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_render_anthropic_multimodal() -> None:
    out = render_anthropic([text_block("hi"), image_block(b"xy")])
    assert out[1]["type"] == "image"
    assert out[1]["source"] == {"type": "base64", "media_type": "image/png", "data": "eHk="}


def test_render_gemini_multimodal() -> None:
    parts = render_gemini_parts([text_block("hi"), image_block(b"xy")])
    assert parts[0] == {"text": "hi"}
    assert parts[1]["inline_data"]["mime_type"] == "image/png"


def test_content_to_text_drops_images() -> None:
    c = [text_block("see this"), image_block(b"xy")]
    assert has_images(c) is True
    assert content_to_text(c) == "see this"


def test_openrouter_body_carries_image() -> None:
    from essarion_build._providers import _OpenRouterProvider

    p = _OpenRouterProvider(api_key="k", model="openai/gpt-4o-mini")
    msgs = [{"role": "user", "content": [text_block("what's here?"), image_block(b"xy")]}]
    body = p._build_body(system="sys", messages=msgs, max_tokens=10)
    user_msg = body["messages"][1]
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][1]["type"] == "image_url"


# ---- executor attaches screenshots only when the model can see ----

def test_executor_attaches_image_for_vision_model() -> None:
    from essarion_build.agent._agent_exec import _attach_images
    from essarion_build.agent._session import Session
    from essarion_build.computer import _actions

    s = Session(id="x", cwd="/tmp", provider="openrouter", model="openai/gpt-4o-mini")
    _actions._PENDING_IMAGES.clear()
    _actions._PENDING_IMAGES.append((b"\x89PNG", "image/png"))
    content = _attach_images("here is the screen", s)
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image"


def test_executor_does_not_send_blind_to_textonly_model() -> None:
    from essarion_build.agent._agent_exec import _attach_images
    from essarion_build.agent._session import Session
    from essarion_build.computer import _actions

    s = Session(id="x", cwd="/tmp", provider="openrouter", model="mistral-7b-instruct")
    _actions._PENDING_IMAGES.clear()
    _actions._PENDING_IMAGES.append((b"\x89PNG", "image/png"))
    content = _attach_images("here is the screen", s)
    assert isinstance(content, str)
    assert "can't view images" in content


def test_no_pending_images_returns_plain_text() -> None:
    from essarion_build.agent._agent_exec import _attach_images
    from essarion_build.agent._session import Session
    from essarion_build.computer import _actions

    _actions._PENDING_IMAGES.clear()
    s = Session(id="x", cwd="/tmp", provider="openrouter", model="openai/gpt-4o-mini")
    assert _attach_images("plain feedback", s) == "plain feedback"
