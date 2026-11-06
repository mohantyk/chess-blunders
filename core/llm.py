"""LLM calls over an OpenAI-compatible endpoint (by default the Ollama server on the Mac mini).

Settings come from the ``llm:`` section of config.yaml (base_url, model,
timeout_s); the OLLAMA_BASE_URL / OLLAMA_MODEL / OLLAMA_API_KEY environment
variables override them. System prompts live in ``core/prompts/*.md``.

Every call returns ``(result, error)``: ``error`` is a short human-readable
reason ("can't reach http://mac-mini:11434/v1: ...") so the UI can show why
an AI suggestion is missing instead of failing silently.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from core.config import load_config

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def load_prompt(name: str) -> str:
    """The text of ``core/prompts/<name>.md``."""
    with open(os.path.join(PROMPTS_DIR, f"{name}.md"), encoding="utf-8") as f:
        return f.read().strip()


def llm_settings() -> dict:
    """{base_url, model, timeout_s, api_key}: config.yaml's llm section, env vars on top."""
    cfg = dict(load_config().get("llm") or {})
    base_url = (os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
                or cfg.get("base_url") or "http://mac-mini:11434/v1")
    model = os.environ.get("OLLAMA_MODEL") or os.environ.get("MODEL_ID") or cfg.get("model")
    api_key = os.environ.get("OLLAMA_API_KEY") or os.environ.get("OPENAI_API_KEY") or "ollama"
    return {"base_url": base_url, "model": model or "gemma4:12b",
            "timeout_s": float(cfg.get("timeout_s") or 90), "api_key": api_key}


def _client(settings: dict):
    """An OpenAI client for the configured endpoint (no retries: errors surface quickly)."""
    from openai import OpenAI
    return OpenAI(api_key=settings["api_key"], base_url=settings["base_url"],
                  timeout=settings["timeout_s"], max_retries=0)


def describe_error(exc: Exception, settings: dict) -> str:
    """A one-line reason for a failed call, naming the server or model involved."""
    import openai
    where = settings["base_url"]
    if isinstance(exc, openai.APITimeoutError):
        return f"{where} didn't answer within {settings['timeout_s']:.0f}s"
    if isinstance(exc, openai.APIConnectionError):
        return f"can't reach {where} ({exc.__cause__ or exc})"
    if isinstance(exc, openai.NotFoundError):
        return f"model {settings['model']} not found on {where}"
    if isinstance(exc, openai.APIStatusError):
        return f"{where} returned HTTP {exc.status_code}: {str(exc)[:120]}"
    return f"{type(exc).__name__}: {str(exc)[:160]}"


def chat_json(system: str, user: str, schema: dict, name: str = "answer",
              max_tokens: int = 400) -> tuple:
    """Ask for a JSON object matching ``schema``; returns (dict or None, error or None).

    Uses structured output (``response_format`` json_schema) and asks the
    model not to think first ("reasoning_effort": "none"), which keeps 8-12B
    models on the Mac mini fast.
    """
    settings = llm_settings()
    try:
        response = _client(settings).chat.completions.create(
            model=settings["model"],
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_schema",
                             "json_schema": {"name": name, "schema": schema}},
            extra_body={"reasoning_effort": "none"},
        )
    except Exception as exc:  # network, HTTP, timeout: report, don't crash the wizard
        return None, describe_error(exc, settings)
    raw = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, f"{settings['model']} returned invalid JSON: {raw[:80]!r}"
    if not isinstance(data, dict):
        return None, f"{settings['model']} returned {type(data).__name__}, not an object"
    return data, None


def get_recommendation(classification: dict) -> tuple:
    """A short coaching paragraph for a saved mistake; returns (text or None, error or None)."""
    settings = llm_settings()
    try:
        response = _client(settings).chat.completions.create(
            model=settings["model"],
            messages=[{"role": "system", "content": load_prompt("recommendation")},
                      {"role": "user", "content": json.dumps(classification, indent=2)}],
            temperature=0.7,
            max_tokens=300,
            extra_body={"reasoning_effort": "none"},
        )
    except Exception as exc:
        return None, describe_error(exc, settings)
    text = (response.choices[0].message.content or "").strip()
    return (text, None) if text else (None, f"{settings['model']} returned an empty answer")


def model_label(settings: Optional[dict] = None) -> str:
    """Short model name for UI captions, e.g. "gemma4:12b"."""
    return (settings or llm_settings())["model"]
