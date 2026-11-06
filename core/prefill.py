"""Wizard pre-fill (PRD F14): engine facts + rule guesses + one LLM call per queued move.

``suggest(item, cfg, ev, llm)`` returns a ``Suggestion`` with a value for
every wizard field it can fill and where each value came from:

* "engine" — computed: the layer from my candidates (F7), "Rushed" from the
  time check, or a rule guess from ``core.position_facts`` (also when the
  LLM picked the same value);
* "ai" — the LLM chose something different from the rules, or wrote it (the
  one-sentence fix).

The F7 layer and the "Rushed" secondary theme are facts and are never
overridden. When the engine or the LLM fails, the other source still fills
what it can and ``error`` says what went wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from core import llm as llm_mod
from core.position_facts import (
    gather_facts, guess_prescription, guess_step, guess_theme,
)

FIELDS = ("step", "layer", "primary_theme", "secondary_theme", "training_prescription",
          "one_sentence_fix")
LAYERS = ("didnt_see", "got_it_wrong")
LAYER_TEXT = {"didnt_see": "the player's in-game candidates did NOT include the engine's best "
                           "move (layer didnt_see)",
              "got_it_wrong": "the player considered a better move during the game but played "
                              "a worse one (layer got_it_wrong)"}


@dataclass
class Suggestion:
    """Pre-filled wizard values for one move, their sources, and any problem."""

    values: dict = field(default_factory=dict)    # field -> value
    sources: dict = field(default_factory=dict)   # field -> "engine" / "ai"
    error: Optional[str] = None
    reason: Optional[str] = None                  # the LLM's one-line why
    facts_text: Optional[str] = None


def response_schema(cfg: dict) -> dict:
    """JSON schema for the LLM answer, with enums from the config lists."""
    return {
        "type": "object",
        "properties": {
            "step": {"type": "integer", "enum": [1, 2, 3, 4]},
            "layer": {"type": "string", "enum": list(LAYERS)},
            "primary_theme": {"type": "string", "enum": list(cfg["primary_themes"])},
            "secondary_theme": {"type": "string", "enum": list(cfg["secondary_themes"])},
            "training_prescription": {"type": "string",
                                      "enum": list(cfg["training_prescriptions"])},
            "fix": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["step", "layer", "primary_theme", "secondary_theme",
                     "training_prescription", "fix", "reason"],
    }


def user_message(item: dict, facts_text: Optional[str], guesses: dict) -> str:
    """The prompt's user part: the move, my candidates and comment, engine facts and guesses."""
    side = item.get("move_side", "")
    lines = [f"Move: {item.get('label') or item.get('move_san')} (the player is {side})."]
    considered = item.get("considered") or []
    lines.append("Moves the player considered during the game: "
                 + (", ".join(considered) if considered else "not recorded") + ".")
    comment = (item.get("annotation") or "").strip()
    lines.append(f'Player\'s comment on the move: "{comment}"' if comment
                 else "Player's comment on the move: none.")
    layer = item.get("layer_prefill")
    lines.append("Candidate check: " + (LAYER_TEXT[layer] if layer in LAYER_TEXT else "unknown")
                 + ".")
    if item.get("rushed"):
        lines.append("Time: the player spent little time on this move although the clock "
                     "allowed more.")
    if item.get("engine_summary"):
        lines.append(item["engine_summary"])
    if facts_text:
        lines += ["", "Engine facts:", facts_text]
    if guesses:
        parts = [f"{k.replace('_', ' ')}: {v}" for k, v in guesses.items() if v is not None]
        lines += ["", "Engine rule guesses: " + "; ".join(parts) + "."]
    return "\n".join(lines)


def suggest(item: dict, cfg: dict, ev: Optional[Callable] = None,
            llm: Optional[Callable] = None) -> Suggestion:
    """Suggestion for one wizard queue item.

    item: a ``build_queue`` entry (fen, move_obj, layer_prefill, ...).
    cfg: the loaded config (theme / prescription lists).
    ev: ``fen -> EngineResult`` evaluator, or None when the engine isn't available.
    llm: ``chat_json``-like callable (default ``core.llm.chat_json``).
    """
    llm = llm or llm_mod.chat_json
    out = Suggestion()
    errors = []

    def put(name, value, source):
        """Record a value and its source."""
        out.values[name] = value
        out.sources[name] = source

    if item.get("layer_prefill") in LAYERS:
        put("layer", item["layer_prefill"], "engine")
    if item.get("secondary_prefill"):
        put("secondary_theme", item["secondary_prefill"], "engine")

    facts, guesses = None, {}
    if ev is not None and item.get("move_obj") is not None:
        try:
            facts = gather_facts(item["fen"], item["move_obj"], ev)
        except Exception as exc:  # engine died, odd position: carry on without facts
            errors.append(f"engine facts unavailable ({exc})")
    if facts is not None:
        out.facts_text = facts.to_text()
        step = guess_step(facts)
        theme = guess_theme(facts, step, cfg["primary_themes"])
        guesses = {"step": step, "primary_theme": theme,
                   "training_prescription": guess_prescription(
                       theme, step, bool(item.get("rushed")), cfg["training_prescriptions"])}
        for name, value in guesses.items():
            if value is not None:
                put(name, value, "engine")

    data, err = llm(llm_mod.load_prompt("wizard_prefill"),
                    user_message(item, out.facts_text, guesses),
                    response_schema(cfg), "wizard_prefill")
    if data is None:
        errors.append(f"AI suggestions unavailable: {err}")
    else:
        allowed = {"step": [1, 2, 3, 4], "layer": list(LAYERS),
                   "primary_theme": cfg["primary_themes"],
                   "secondary_theme": cfg["secondary_themes"],
                   "training_prescription": cfg["training_prescriptions"]}
        fixed = {name for name in ("layer", "secondary_theme") if name in out.values}
        for name, choices in allowed.items():
            value = data.get(name)
            if name in fixed or value not in choices:
                continue
            same = out.values.get(name) == value and out.sources.get(name) == "engine"
            put(name, value, "engine" if same else "ai")
        fix = (data.get("fix") or "").strip()
        if fix:
            put("one_sentence_fix", fix, "ai")
        out.reason = (data.get("reason") or "").strip() or None
    out.error = "; ".join(errors) or None
    return out
