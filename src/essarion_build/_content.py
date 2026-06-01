"""Multimodal message content — the seam that lets the model SEE.

A message's ``content`` has always been a plain string. To send images (a
screenshot, a diagram) we allow it to also be a list of neutral blocks:

    [{"type": "text", "text": "what changed?"},
     {"type": "image", "media_type": "image/png", "data": "<base64>"}]

Each provider renders that list into its own native multimodal shape. A plain
string still flows through untouched, so nothing that doesn't use images is
affected. Build blocks with :func:`text_block` / :func:`image_block`.
"""

from __future__ import annotations

import base64
from typing import Any, Union

Content = Union[str, list]


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def image_block(data: "bytes | str", media_type: str = "image/png") -> dict:
    """An image block. `data` may be raw bytes or an already-base64 string."""
    if isinstance(data, bytes):
        data = base64.b64encode(data).decode("ascii")
    return {"type": "image", "media_type": media_type, "data": data}


def has_images(content: Content) -> bool:
    return isinstance(content, list) and any(
        b.get("type") == "image" for b in content if isinstance(b, dict)
    )


def content_to_text(content: Content) -> str:
    """Flatten to text (drops images) — for text-only providers."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def render_openai(content: Content) -> Any:
    """OpenAI / OpenRouter chat content blocks."""
    if isinstance(content, str):
        return content
    out: list[dict] = []
    for b in content:
        if b.get("type") == "text":
            out.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "image":
            url = f"data:{b.get('media_type', 'image/png')};base64,{b['data']}"
            out.append({"type": "image_url", "image_url": {"url": url}})
    return out


def render_anthropic(content: Content) -> Any:
    """Anthropic Messages content blocks."""
    if isinstance(content, str):
        return content
    out: list[dict] = []
    for b in content:
        if b.get("type") == "text":
            out.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "image":
            out.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": b.get("media_type", "image/png"),
                    "data": b["data"],
                },
            })
    return out


def render_gemini_parts(content: Content) -> list:
    """Gemini `parts` for one message."""
    if isinstance(content, str):
        return [{"text": content}]
    parts: list[dict] = []
    for b in content:
        if b.get("type") == "text":
            parts.append({"text": b["text"]})
        elif b.get("type") == "image":
            parts.append({"inline_data": {"mime_type": b.get("media_type", "image/png"), "data": b["data"]}})
    return parts
