"""Optional AI helper utilities for Atelier."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from .io import warn
from .models import AIConfig

_OPENAI_BASE_URL = "https://api.openai.com/v1"
_OPENAI_CHAT_PATH = "/chat/completions"
_DEFAULT_TIMEOUT = 20
_MAX_CONTEXT_CHARS = 4000


def ai_enabled(config: AIConfig) -> bool:
    """Return whether AI helpers are configured."""
    if config.provider == "none":
        return False
    if not config.model:
        return False
    return True


def ai_disabled_reason(config: AIConfig) -> str | None:
    """Return the reason AI helpers are disabled, if any."""
    if config.provider == "none":
        return "ai.provider is 'none'"
    if not config.model:
        return "ai.model is not set"
    return None


def suggest_branch_names(
    config: AIConfig,
    context: str,
    *,
    count: int = 3,
) -> list[str]:
    """Return AI-suggested branch name candidates."""
    if not ai_enabled(config):
        return []
    prompt = (
        "Suggest short git branch name slugs for the task below."
        "\n- Use lowercase letters, digits, and hyphens only."
        "\n- Do not include prefixes like 'feature/' or usernames."
        "\n- Return one suggestion per line without bullets or numbering."
        "\n\nContext:\n"
        f"{_truncate_context(context)}"
    )
    response = complete_text(
        config,
        system_prompt="You create concise git branch name slugs.",
        user_prompt=prompt,
        max_tokens=200,
        temperature=0.2,
    )
    if not response:
        return []
    return _parse_suggestions(response, count=count)


def draft_success_md(config: AIConfig, context: str) -> str | None:
    """Return an AI-drafted SUCCESS.md based on ticket context."""
    if not ai_enabled(config):
        return None
    outline = (
        "# Success Contract\n\n"
        "## Goal\n\n"
        "## Context\n\n"
        "## Constraints / Considerations\n\n"
        "## Success Criteria\n\n"
        "## Verification\n\n"
        "## Notes\n"
    )
    prompt = (
        "Draft a SUCCESS.md for the ticket context below."
        "\n- Fill in each section with concise bullet points or short paragraphs."
        "\n- Keep it scoped to the ticket."
        "\n- Return markdown only, no surrounding code fences."
        "\n\nTemplate:\n"
        f"{outline}\n"
        "Ticket context:\n"
        f"{_truncate_context(context)}"
    )
    response = complete_text(
        config,
        system_prompt="You draft concise SUCCESS.md files for software tasks.",
        user_prompt=prompt,
        max_tokens=800,
        temperature=0.2,
    )
    if not response:
        return None
    cleaned = _strip_code_fences(response.strip())
    if not cleaned:
        return None
    if not cleaned.startswith("#"):
        cleaned = f"# Success Contract\n\n{cleaned}"
    return cleaned.rstrip() + "\n"


def complete_text(
    config: AIConfig,
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str | None:
    """Return a raw completion string for the configured AI provider."""
    if not ai_enabled(config):
        return None
    if config.provider != "openai":
        warn(f"unsupported AI provider {config.provider!r}")
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        warn("OPENAI_API_KEY is not set; skipping AI request")
        return None
    return _openai_chat_completion(
        api_key=api_key,
        model=config.model or "",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _openai_chat_completion(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str | None:
    base_url = os.environ.get("OPENAI_BASE_URL", _OPENAI_BASE_URL).rstrip("/")
    url = f"{base_url}{_OPENAI_CHAT_PATH}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_DEFAULT_TIMEOUT) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        warn(
            "AI request failed "
            f"({exc.code} {exc.reason})"
            f"{': ' + detail if detail else ''}"
        )
        return None
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        warn(f"AI request failed: {reason}")
        return None
    except json.JSONDecodeError:
        warn("AI request returned invalid JSON")
        return None
    return _extract_openai_content(data)


def _extract_openai_content(payload: dict) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    if not content:
        return None
    return str(content).strip() or None


def _truncate_context(text: str) -> str:
    if len(text) <= _MAX_CONTEXT_CHARS:
        return text
    return text[:_MAX_CONTEXT_CHARS].rstrip() + "\n...(truncated)"


def _parse_suggestions(text: str, *, count: int) -> list[str]:
    raw_parts = re.split(r"[\n,]+", text)
    suggestions: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        candidate = part.strip().strip("`")
        candidate = re.sub(r"^[\s\-\*\d\.\)]+", "", candidate).strip()
        if not candidate:
            continue
        normalized = candidate.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        suggestions.append(candidate)
        if len(suggestions) >= count:
            break
    return suggestions


def _strip_code_fences(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()
