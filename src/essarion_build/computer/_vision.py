"""Model vision-capability check.

The CDP / accessibility-tree / OCR tiers are all text and run on any model. The
screenshot tier needs a multimodal model. Before using vision we check the
configured model and, if it can't see images, prompt the user to switch instead
of silently sending a blind request.
"""

from __future__ import annotations

# Substring hints. Conservative: a positive hint means "known to see images".
_VISION_HINTS = (
    "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-4-vision", "o1", "o3", "o4",
    "claude-3", "claude-3.5", "claude-3.7", "claude-sonnet-4", "claude-opus-4",
    "claude-haiku-4", "sonnet-4", "opus-4", "haiku-4",
    "gemini-1.5", "gemini-2", "gemini-pro-vision", "gemini-flash",
    "llava", "qwen2-vl", "qwen2.5-vl", "pixtral", "llama-3.2", "llama3.2",
)
_NO_VISION_HINTS = (
    "gpt-3.5", "claude-2", "claude-instant", "text-embedding", "embed",
    "gemma", "mistral-7b", "mixtral", "codellama", "deepseek-coder",
    "qwen2.5-coder", "starcoder", "phi-2",
)


def model_supports_vision(provider: str, model: str) -> bool | None:
    """True / False / None(unknown) for whether the model can see images."""
    m = (model or "").lower()
    if any(h in m for h in _NO_VISION_HINTS):
        return False
    if any(h in m for h in _VISION_HINTS):
        return True
    return None


def vision_prompt(provider: str, model: str) -> str:
    return (
        f"the screenshot/vision tier needs a vision-capable model, but "
        f"{provider}/{model} can't see images.\n"
        "Switch with e.g. `--model anthropic/claude-haiku-4-5` or "
        "`--model openai/gpt-4o`, or run `/model <name>` in the REPL, then retry. "
        "(The text tiers — DOM/accessibility/console digests — work on any model.)"
    )


def check_vision(provider: str, model: str) -> tuple[bool, str]:
    """(ok, message). ok=False with a switch-model prompt when the model is
    known to lack vision; unknown models pass with an empty message."""
    cap = model_supports_vision(provider, model)
    if cap is False:
        return False, vision_prompt(provider, model)
    return True, ""
