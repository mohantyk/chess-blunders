"""LLM integration via OpenAI-compatible Ollama endpoint."""

import json
import os
from openai import OpenAI

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("OLLAMA_API_KEY", os.environ.get("OPENAI_API_KEY", "ollama"))
        base_url = (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "http://localhost:11434/v1"
        )
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def _model():
    return (
        os.environ.get("OLLAMA_MODEL")
        or os.environ.get("MODEL_ID")
        or "llama3"
    )


PREFILL_SYSTEM = """You are a chess coach assistant. Given a player's annotation of their own chess mistake, classify it using two dimensions:

1. Which thinking step broke down?
   - Step 1: player missed opponent's threat or intention
   - Step 2: player missed their own tactic or forcing move
   - Step 3: player chose the wrong strategic plan or piece improvement
   - Step 4: player failed to check opponent's response before playing

2. Did they see the possibility?
   - didnt_see: the idea never occurred to them
   - got_it_wrong: they saw something but miscalculated or misjudged

Respond only with valid JSON like: {"step": 2, "layer": "didnt_see"}
No explanation, no markdown, just the JSON object."""


RECOMMEND_SYSTEM = """You are a chess coach. Given a classified chess mistake, write a short 3-5 sentence recommendation explaining what specific pattern the player needs to train, why the suggested puzzles address their blind spot, and one concrete piece of advice for their next game. Be direct and specific. Do not repeat the classification back to them."""


def prefill_classification(annotation: str):
    """
    Given a PGN annotation comment, return {"step": int, "layer": str} or None on failure.
    """
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": PREFILL_SYSTEM},
                {"role": "user", "content": annotation},
            ],
            temperature=0,
            max_tokens=64,
        )
        raw = response.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception:
        return None


def get_recommendation(classification: dict):
    """
    Given full classification dict, return a short recommendation paragraph or None on failure.
    """
    try:
        client = _get_client()
        user_msg = json.dumps(classification, indent=2)
        response = client.chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": RECOMMEND_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            max_tokens=256,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return None
