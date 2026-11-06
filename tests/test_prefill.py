"""Wizard pre-fill: engine rules + LLM answer, sources, fallbacks and facts never overridden."""

import chess

from core.config import DEFAULTS
from core.prefill import response_schema, suggest, user_message
from tests.stub_engine import StubEngine
from tests.test_position_facts import FORK_FEN, after_fen, null_fen

CFG = {"primary_themes": DEFAULTS["primary_themes"] + ["Hanging Piece"],
       "secondary_themes": DEFAULTS["secondary_themes"],
       "training_prescriptions": DEFAULTS["training_prescriptions"]}


def fork_stub():
    """Best move Nc7+ (fork); my Kd2 is quiet; no threat."""
    stub = StubEngine(0).set_fen(FORK_FEN, [("Nc7+", 500)]).set_fen(null_fen(FORK_FEN), 500)
    stub.set_fen(after_fen(FORK_FEN, "Kd2"), [("Kd7", 0)])
    return stub


def item(**kw):
    """A queue item for 1.Kd2 in FORK_FEN."""
    board = chess.Board(FORK_FEN)
    base = {"fen": FORK_FEN, "move_obj": board.parse_san("Kd2"), "move_san": "Kd2",
            "move_side": "white", "label": "1.Kd2", "layer_prefill": None,
            "secondary_prefill": None, "annotation": None, "considered": [],
            "engine_summary": "Engine: best was Nc7+ (+5.00); you played Kd2 (0.00).",
            "rushed": False}
    base.update(kw)
    return base


def llm_answer(answer=None, error=None, seen=None):
    """A chat_json stand-in returning ``answer`` (or the error); records prompts in ``seen``."""
    def call(system, user, schema, name):
        """Record the prompt and answer."""
        if seen is not None:
            seen.append((system, user, schema))
        return answer, error
    return call


GOOD = {"step": 2, "layer": "didnt_see", "primary_theme": "Fork", "secondary_theme": "None",
        "training_prescription": "Fork puzzles",
        "fix": "Look for checks that hit two pieces first.", "reason": "Missed Nc7+ fork."}


def test_llm_agrees_with_rules():
    """Values the LLM shares with the rules are marked engine; its own ones ai."""
    seen = []
    s = suggest(item(), CFG, ev=fork_stub(), llm=llm_answer(GOOD, seen=seen))
    assert s.values["step"] == 2 and s.sources["step"] == "engine"
    assert s.values["primary_theme"] == "Fork" and s.sources["primary_theme"] == "engine"
    assert s.sources["training_prescription"] == "engine"
    assert s.sources["layer"] == "ai" and s.sources["secondary_theme"] == "ai"
    assert s.values["one_sentence_fix"].startswith("Look for checks")
    assert s.error is None and s.reason == "Missed Nc7+ fork."
    system, user, schema = seen[0]
    assert "thinking step" in system
    assert "Engine's best move: Nc7+ (check)" in user and "Engine rule guesses: step: 2" in user
    assert schema["properties"]["primary_theme"]["enum"] == CFG["primary_themes"]


def test_llm_overrides_rule_marked_ai():
    """A different LLM choice wins and is marked ai."""
    s = suggest(item(), CFG, ev=fork_stub(), llm=llm_answer({**GOOD, "step": 3}))
    assert s.values["step"] == 3 and s.sources["step"] == "ai"


def test_facts_never_overridden():
    """The F7 layer and the Rushed theme stay, whatever the LLM says."""
    it = item(layer_prefill="got_it_wrong", secondary_prefill="Rushed (time available)",
              rushed=True)
    s = suggest(it, CFG, ev=fork_stub(), llm=llm_answer(GOOD))
    assert s.values["layer"] == "got_it_wrong" and s.sources["layer"] == "engine"
    assert s.values["secondary_theme"] == "Rushed (time available)"


def test_llm_failure_falls_back_to_rules():
    """No LLM: rule values are still filled; the error says why; no fix."""
    s = suggest(item(), CFG, ev=fork_stub(), llm=llm_answer(error="can't reach mac-mini"))
    assert s.values["step"] == 2 and s.values["primary_theme"] == "Fork"
    assert "one_sentence_fix" not in s.values
    assert s.error == "AI suggestions unavailable: can't reach mac-mini"


def test_invalid_llm_values_ignored():
    """Values outside the allowed lists are dropped."""
    s = suggest(item(), CFG, ev=fork_stub(),
                llm=llm_answer({**GOOD, "primary_theme": "Made up", "step": 9}))
    assert s.values["primary_theme"] == "Fork" and s.sources["primary_theme"] == "engine"
    assert s.values["step"] == 2


def test_without_engine_llm_only():
    """No evaluator: the LLM still runs on the comment and summary."""
    seen = []
    s = suggest(item(annotation="I was afraid of Ra2"), CFG, ev=None,
                llm=llm_answer(GOOD, seen=seen))
    assert s.values["step"] == 2 and s.sources["step"] == "ai"
    assert 'Player\'s comment on the move: "I was afraid of Ra2"' in seen[0][1]
    assert "Engine facts" not in seen[0][1]


def test_engine_error_reported():
    """An evaluator that fails is reported but doesn't stop the LLM."""
    def broken(fen):
        """Evaluator that always fails."""
        raise RuntimeError("engine died")
    s = suggest(item(), CFG, ev=broken, llm=llm_answer(GOOD))
    assert "engine facts unavailable (engine died)" in s.error and s.values["step"] == 2


def test_user_message_mentions_candidates_and_time():
    """Considered moves, the F7 layer and rushing appear in the prompt."""
    text = user_message(item(considered=["Kd2", "Nc7+"], layer_prefill="got_it_wrong",
                             rushed=True), None, {})
    assert "considered during the game: Kd2, Nc7+." in text
    assert "considered a better move" in text and "little time" in text


def test_schema_requires_every_field():
    """The JSON schema asks for every wizard field."""
    assert set(response_schema(CFG)["required"]) == {
        "step", "layer", "primary_theme", "secondary_theme", "training_prescription", "fix",
        "reason"}
