"""core/llm.py: settings, prompt files, structured JSON calls and readable errors (no network)."""

from types import SimpleNamespace

import httpx
import openai
import pytest

from core import llm


class FakeClient:
    """Stands in for openai.OpenAI: returns ``content`` or raises ``exc``; records requests."""

    def __init__(self, content=None, exc=None):
        """Configure the canned answer or error."""
        self.content, self.exc, self.requests = content, exc, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        """Record the request and answer it."""
        self.requests.append(kwargs)
        if self.exc:
            raise self.exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=self.content))])


@pytest.fixture
def fake(monkeypatch):
    """Install a FakeClient factory; returns a setter for the next client."""
    box = {}
    monkeypatch.setattr(llm, "_client", lambda settings: box["client"])
    for var in ("OLLAMA_BASE_URL", "OPENAI_BASE_URL", "OLLAMA_MODEL", "MODEL_ID"):
        monkeypatch.delenv(var, raising=False)

    def use(**kw):
        """Make the next call use FakeClient(**kw)."""
        box["client"] = FakeClient(**kw)
        return box["client"]
    return use


def test_settings_from_config_and_env(monkeypatch):
    """config.yaml's llm section is the default; env vars override it."""
    for var in ("OLLAMA_BASE_URL", "OPENAI_BASE_URL", "OLLAMA_MODEL", "MODEL_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm, "load_config", lambda: {"llm": {
        "base_url": "http://box:1/v1", "model": "m1", "timeout_s": 5}})
    s = llm.llm_settings()
    assert (s["base_url"], s["model"], s["timeout_s"]) == ("http://box:1/v1", "m1", 5.0)
    monkeypatch.setenv("OLLAMA_MODEL", "m2")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://other/v1")
    s = llm.llm_settings()
    assert (s["base_url"], s["model"]) == ("http://other/v1", "m2")


def test_prompts_are_files():
    """System prompts load from core/prompts."""
    assert "thinking step" in llm.load_prompt("wizard_prefill")
    assert llm.load_prompt("recommendation").startswith("You are a chess coach")


def test_chat_json_structured_request(fake):
    """A valid answer is parsed; the request asks for the schema and no thinking."""
    client = fake(content='{"step": 2}')
    data, err = llm.chat_json("sys", "user", {"type": "object"}, name="prefill")
    assert (data, err) == ({"step": 2}, None)
    req = client.requests[0]
    assert req["response_format"]["json_schema"] == {"name": "prefill",
                                                     "schema": {"type": "object"}}
    assert req["extra_body"] == {"reasoning_effort": "none"}
    assert req["messages"][0] == {"role": "system", "content": "sys"}


def test_chat_json_invalid_json(fake):
    """Non-JSON output is an error, not a crash."""
    fake(content="Step 2, I think")
    data, err = llm.chat_json("s", "u", {})
    assert data is None and "invalid JSON" in err


def test_errors_are_readable(fake):
    """Connection and missing-model errors name the server / model."""
    request = httpx.Request("POST", "http://mac-mini:11434/v1/chat/completions")
    fake(exc=openai.APIConnectionError(request=request))
    _, err = llm.chat_json("s", "u", {})
    assert err.startswith("can't reach ")
    response = httpx.Response(404, request=request)
    fake(exc=openai.NotFoundError("model not found", response=response, body=None))
    _, err = llm.get_recommendation({"step": 1})
    assert err.startswith("model ") and "not found" in err


def test_recommendation_text(fake):
    """get_recommendation returns the text; an empty answer is an error."""
    fake(content="  Train forks.  ")
    assert llm.get_recommendation({"step": 2}) == ("Train forks.", None)
    fake(content="")
    text, err = llm.get_recommendation({"step": 2})
    assert text is None and "empty" in err


def test_tests_never_reach_the_real_server():
    """The autouse guard in conftest blocks real clients."""
    data, err = llm.chat_json("s", "u", {})
    assert data is None and "disabled in tests" in err
