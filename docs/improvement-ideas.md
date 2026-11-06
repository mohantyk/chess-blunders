# Improvement ideas (fresh-eyes review, 2026-11-05)

From a read-only review of the code, PRD and game 1 (Shrey2019) data. Status in brackets.

## Fix first (bugs that undermine the app's purpose)
1. **Puzzles + recommendation never seen.** `_on_save` shows the results box, then `_load_move` hides it at once; nothing else reads `puzzle_urls` / `llm_recommendation`. Add a Training panel on Patterns. [in progress]
2. **Theme → puzzle map gaps.** "Hanging Piece", "Hanging Pawn", "3-ply", "Evaluation" unmapped; "Calculation error" → `hangingPiece` is wrong. Ask for a puzzle theme when adding via "Other…". 3-ply / calculation themes → `mateIn2`. Add "3-ply calculation" as a built-in theme. [in progress]
3. **Near-best moves queued as mistakes.** Top set capped at 2 lines (`core/checks.py` `check_decisions`), so 19...Rfd8 (lost 3.9 < 5 window) became `candidate_miss` + "rushed mistake". [in progress]
4. **Defaults saved as if chosen.** If pre-fill fails, Save stores Step 1 / "Fork". Untouched, un-suggested fields should require a choice. [in progress]
5. **Tk called from a worker thread** in the wizard's recommendation step (`_async_enrich` → `self.after`); errors after the wizard is gone. [in progress]

## Better use of existing data
6. Per-game habit counts on every move: "best was forcing, I played quiet" (step 2) and "ignored opponent's threat" (step 1, null-move threat). E.g. Nf4+ was also best at move 13.
7. Auto-classify every costly move (loss ≥ 5) with `guess_step`; chart the step distribution; wizard confirms.
8. Score post-game judgement: Choice-quiz picks (`findings.user_answer`) and missing-eval bands (`findings.user_value`).
9. Time spent vs damage per game (clock data + move losses); per-game trends instead of needing 2 months.

## New capabilities
10. Spaced-repetition drill of past mistakes, reusing the quiz buttons (PRD future idea).
11. F16 "Explain" / "Answer my question" — `PositionFacts.to_text()` already builds the input.
12. Separate habits ("3-ply", "Calculation", "Evaluation") from tactic themes.
13. Review progress: "N open" counter + jump to next open finding (11 of 17 open in game 1).
14. Reword "Did you see it?" per step ("Did you see the reply that punished it?") with evidence ("You listed Nf4+ otb").

## Other risks noted
- A custom primary theme is written to config.yaml even if Save then fails validation.
- Pre-fill suggestions are memory-only; after a restart each move waits for the LLM again.
- First LLM call on a cold Mac mini took ~2.5 min.
