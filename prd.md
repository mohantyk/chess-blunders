# PRD — Analysis Review: engine checks on my own hand analysis

Extension of the existing **chess-patterns** app (CustomTkinter + python-chess + SQLite). Read `SPEC.md` and `README.md` first; this document only describes what is new or changed.

---

## 1. Background and goal

My workflow after a game:

1. Put the game into a Lichess study (all games go into **one** study, one chapter per game).
2. Analyse it by hand, **without an engine**: add variations for moves I considered, add an eval symbol (=, +=, ±, +-, etc.) at the end of lines, write comments, draw arrows.
3. Only then use an engine — but not the usual full-game "blunder / mistake / inaccuracy" report, which isn't very helpful.

**Goal:** use Stockfish to check *my analysis* rather than the game, find out where my thinking went wrong, and feed the results into the existing mistakes database so I can see patterns over time — both in my game mistakes and in the quality of my analysis.

Guiding principles:

- **The engine judges, the LLM only explains.** No LLM is ever asked to find moves or evaluate positions on its own.
- **Hints before answers.** Every finding first tells me *where* to look; the engine's answer is revealed only when I ask.
- **Focused, not exhaustive.** A short list of meaningful findings per game, never a move-by-move engine dump.

---

## 2. Scope

### In scope (this PRD)

| # | Feature | Milestone |
|---|---|---|
| F1 | Bug fix: `?` / `??` NAGs are swapped in the existing parser | M1 |
| F2 | Study import with incremental sync (only new chapters) | M1 |
| F3 | Analysis tree parsing (variations, `otb` tags, eval symbols, glyphs, arrows, clocks) | M1 |
| F4 | Engine service (Stockfish, local or on the Mac mini) with cache | M2 |
| F5 | Check 1 — Is my evaluation right? | M2 |
| F6 | Check 2 — Did my in-game candidates include the engine's best move(s)? | M2 |
| F7 | Check 3 — Did I pick the best of my candidates? | M2 |
| F8 | Check 4 — Does a line in my analysis have a hole? | M2 |
| F9 | Blind spots — critical moments I didn't analyse at all | M2 |
| F10 | Time use | M2 |
| F11 | Command-line report (for testing before the UI exists) | M2 |
| F12 | Database: store runs, findings, decision points | M3 |
| F13 | Review screen (read-only analysis viewer with hints → answers) | M3 |
| F14 | Wizard pre-fill from engine findings | M4 |
| F15 | Patterns dashboard: analysis-skill metrics | M4 |
| F16 | LLM explanations (later phase) | M5 |

### Explicitly out of scope (do not build)

- Writing anything back to Lichess (no study write access).
- Judging my **opponent's actual game moves**. (Opponent moves *inside my own analysis lines* are still checked — see F8.)
- Automatic tactic naming (fork, pin, …) — I pick the theme myself in the wizard.
- Opening repertoire detection.
- Sending board images to an LLM / vision models.
- Chess-specific models such as Queen.
- An interactive board where I can move pieces inside the app (the viewer is read-only; "Open in Lichess" covers free exploration).
- A full-game engine report or accuracy score.

---

## 3. Conventions I follow in my studies (input contract)

These are the conventions the parser must understand. Anything not following them must degrade gracefully, never crash.

| What | How I write it in the Lichess study | Meaning for the tool |
|---|---|---|
| In-game candidate | The word `otb` (case-insensitive, whole word) in the comment of the **first move** of a variation. Accept it either after the move (`node.comment`) or before it (`node.starting_comment`). | This alternative was considered **during the game**. |
| Post-game idea | A variation **without** `otb`. | Found while analysing afterwards. Still checked for eval and holes, but **not** counted as an in-game candidate. |
| Played move | The mainline move. | Always counts as an in-game candidate. |
| My evaluation | Lichess eval glyphs, exported as NAGs: `$10` (=), `$13` (unclear), `$14` (+=), `$15` (=+), `$16` (±), `$17` (∓), `$18` (+-), `$19` (-+). | My claim about the position after that move. |
| Swindle line | The word `swindle` in the comment of any move in the line. | Skip the eval check (F5) for that line — objective accuracy doesn't matter there. |
| Move glyphs | `!` `$1`, `?` `$2`, `!!` `$3`, `??` `$4`, `!?` `$5`, `?!` `$6`, `□` `$7` (only move). | My claim about the quality of the move. |
| Arrows / circles | `[%cal ...]`, `[%csl ...]` inside comments. | Threats/plans I noticed. Displayed in the viewer; not judged in v1. |
| Clock | `[%clk h:mm:ss]` on mainline moves (time remaining after the move). | Used for F10. |

Older games (including the existing 11 in the database and the two sample games) have **no `otb` tags**. For those, candidate statistics are reported as "unknown", not as misses.

---

## 4. Feature details

### F1 — Bug fix: swapped mistake/blunder NAGs

In `core/pgn_parser.py`, `BLUNDER_NAGS = {2}` and `MISTAKE_NAGS = {4}` are reversed. In PGN (and python-chess), `$2` = `?` (mistake) and `$4` = `??` (blunder): `chess.pgn.NAG_MISTAKE == 2`, `chess.pgn.NAG_BLUNDER == 4`. Example from the sample game: `8. Be2?` parses as NAG 2 and `29. Rff1??` as NAG 4, so today the app labels Be2 a blunder and Rff1 a mistake.

- Fix the constants (use the python-chess named constants).
- Provide a one-off migration that swaps `flag_type` for existing rows **only where** the original PGN glyph can be re-read from `games.pgn_raw` (re-parse each game, match by move number + side + SAN). Print what changed. Do not guess for rows that can't be matched.

**Acceptance:** with the sample PGN, 8.Be2 → `mistake`, 29.Rff1 → `blunder`.

### F2 — Study import with incremental sync

All my games go into the same study. Running the app again must **only pick up chapters that are not yet in the database**.

**Sources (both supported):**

1. **Study URL / ID in config** (preferred): `lichess_study_id` in `config.yaml`. A "Check for new games" button on the Home screen downloads the whole study via `GET https://lichess.org/api/study/{studyId}.pgn?clocks=true&comments=true&variations=true`. For private studies, send `Authorization: Bearer $LICHESS_TOKEN` from `.env` (read-only token, scope `study:read`). No write scope is needed or wanted.
2. **Pasted / uploaded PGN** (existing text box): may contain one or many chapters (a whole-study export). The current parser reads only the first game — change it to read all games.

**De-duplication key, in order of preference:**

1. `ChapterURL` header (e.g. `https://lichess.org/study/YYeDmlVd/zChpvsut`) — unique per chapter.
2. `Site` / `GameId` header (the original game).
3. Fallback: SHA-256 of the mainline SAN moves.

Store the key in a new `games.source_key` column (unique index). For the existing 11 games, backfill `source_key` by re-parsing `pgn_raw` headers.

**Behaviour:**

- After fetching/pasting, show a list of chapters with status: **New**, **Already imported**, or **Updated** (already imported, but the analysis changed since — detect by storing `analysis_hash`: SHA-256 of the PGN with `[%clk]`/`[%eval]` stripped and whitespace normalised).
- New chapters are pre-selected; already-imported ones are hidden behind a "show all" toggle; updated ones are shown but not pre-selected.
- Re-running an updated chapter creates a new analysis run (F12) and replaces that chapter's open findings; wizard entries I already saved in `blunders` are **never** deleted or modified.
- My colour is inferred automatically: `lichess_username` in `config.yaml` (`i_will_analyze_games`) matched against `White`/`Black` headers. Fall back to the existing White/Black buttons only if no match.

**Acceptance:**
- Importing the sample two-chapter PGN twice → second time shows 0 new chapters.
- Adding a variation to one chapter and re-importing → that chapter shows as "Updated".

### F3 — Analysis tree parsing

New module, e.g. `core/analysis_tree.py`, built on `chess.pgn`. It produces a structure the checks can use without touching PGN text again:

- For every node: path from root (SAN list), FEN before/after, side to move, move glyph NAGs, eval NAG, cleaned comment, `otb` flag, `swindle` flag, arrows/circles, clock.
- **Mainline decision points:** mainline positions where **it was my move** and at least one variation branches from the same parent. Each has: played move, `otb` candidates (played move + tagged siblings), post-game candidates (untagged siblings).
- **Analysis lines:** every variation (recursively, including nested sub-variations), with its branch point, the side that played its first move, and its last node.

Helper: `my_color` drives everything; the tree is always read from my perspective.

### F4 — Engine service

New module, e.g. `core/engine.py`, wrapping `chess.engine` (python-chess UCI).

- **Where it runs:** configurable command in `config.yaml`:
  ```yaml
  engine:
    command: ["stockfish"]            # local, e.g. /opt/homebrew/bin/stockfish
    # command: ["ssh", "mac-mini.local", "/opt/homebrew/bin/stockfish"]   # run on the Mac mini
    threads: 4
    hash_mb: 512
    depth: 20          # or use time_ms instead
    time_ms: null
    multipv: 3
  ```
  python-chess's `popen_uci` accepts a command list, so running Stockfish on the Mac mini over SSH (Remote Login enabled, key-based auth) works without any extra server. Default to local.
- **Scores** are converted to **win percentage** from the side-to-move's or my perspective using the Lichess formula:
  `win% = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)`. Mate scores map to 0/100.
  All thresholds below are in win-percentage **points**, so a 2-pawn error at +6 barely registers while a 1-pawn error near 0.00 does.
- **Cache:** SQLite table `engine_cache (fen, depth, multipv, result_json, engine_id)`. Same FEN + settings → no re-analysis. Re-runs of updated chapters should be fast.
- **Runs off the UI thread** with a progress callback (positions done / total) so the window never freezes.
- Clear error if the engine command fails ("Stockfish not found — set engine.command in config.yaml").

### F5 — Check 1: Is my evaluation right?

Applies to **every node that has an eval NAG**, on the mainline or in any variation, plus **every line end without one**.

- Map my eval NAG to a band. Default band edges (white's perspective, in pawns; configurable as `eval_bands`): `=` < 0.5; `+=` / `=+` 0.5–1.2; `±` / `∓` 1.2–2.5; `+-` / `-+` > 2.5.
- Map the engine's eval of the same position to a band the same way.
- Result per claim:
  - **Match** — same band.
  - **Close** — adjacent band on the same side (e.g. `+=` vs `±`). Shown as info, not a finding.
  - **Wrong** — two or more bands apart, **or** opposite sides of `=` (I think White is better, engine says Black). This is a finding.
- `$13` (unclear): no verdict, but show the engine's band in the viewer.
- Line ends **without** an eval: finding of type `missing_eval` ("You didn't commit to an evaluation here"). In the viewer I'm asked to pick a band **before** the engine's is revealed (F13).
- Lines containing `swindle`: skip.
- **Move-glyph check (should-have):** for my glyphs `?`, `??`, `?!`, `!`, `!!`, `!?`, `□` on my own moves, compare with the engine's win% loss for that move. Flag clear disagreements (e.g. I marked `?!` but it's the engine's top move; I marked `□` but there are other moves within 5 points). Low priority — build after the four checks work.

### F6 — Check 2: Did my in-game candidates include the engine's best?

At each **mainline decision point** (F3) that has at least one `otb`-tagged alternative:

- Run the engine with MultiPV on the position before my move.
- **Engine top set** = the best move plus any other move within `candidate_window` (default **5** win% points) of it, capped at 2 moves ("top 1, or top 2 if the evals are similar").
- **Hit** if any `otb` candidate (including the played move) is in the engine top set.
- Separately record whether any **post-game** candidate is in the top set ("your later analysis found it").

Decision points with variations but no `otb` tags: record candidates as `unknown`, but still compute the post-game hit.

### F7 — Check 3: Did I pick the best of my candidates?

At each mainline decision point with **two or more `otb` candidates**:

- Evaluate each `otb` candidate (engine eval after the move).
- **Chose best** if the played move is within `chose_window` (default **5** win% points) of the best `otb` candidate.
- Otherwise a finding of type `chose_worse`: "You considered X, which was better than the move you played."

**Pre-fill mapping for the wizard (F14):**

| Situation | `layer` pre-fill |
|---|---|
| Engine best not among my `otb` candidates | `didnt_see` |
| Engine best among my `otb` candidates, but I played a worse one | `got_it_wrong` |
| I played the best | no finding |

### F8 — Check 4: Does a line in my analysis have a hole?

For **every analysis line** (all variations, nested ones included), walk move by move **starting from the second move** of the line. (The first move is the hypothesis being explored — "what if I play X / what if they play Y" — and is judged by F6/F7 or not at all.)

For each move: compare the engine's best eval in the position before it with the eval after the line's move, from the mover's perspective. If the loss ≥ `line_break_threshold` (default **10** win% points):

- **My move** in the line → finding `line_break_own`: "Your line has a hole: X is a mistake here; better is Y."
- **Opponent's move** in the line → finding `line_break_opp`: "You assumed a weaker reply. The opponent's best answer here is Y." This is the blunder-check failure (Step 4 in my thinking model) and matters most to me.

Report only the **first** break per line; later moves in a broken line are not judged.

### F9 — Blind spots

My **mainline moves** that I did **not** analyse at all (no variation branching there, no glyph, no comment) where the engine's win% loss ≥ `blind_spot_threshold` (default **10** points).

- Report at most `blind_spot_max` (default **3**) per game, largest loss first.
- Moves I marked with `?` / `??` / `?!` or commented on are **not** blind spots — I noticed them.

### F10 — Time use

From `[%clk]` and the `TimeControl` header (e.g. `900+10`):

- **Time spent on each of my moves** = my clock after my previous move − my clock after this move + increment.
- Attach `time_spent_s` and `clock_remaining_s` to every finding on a mainline move and to every wizard entry.
- Finding `rushed`: a move that is a finding (blunder/mistake glyph, blind spot, `chose_worse`, candidate miss) **and** took less than `rushed_seconds` (default **30 s**) while I had more than `rushed_clock_fraction` (default **50%**) of the starting time left. Example from the sample game: 29.Rff1?? took ~22 s with 13:32 remaining in 15+10.
- Add the secondary theme **"Rushed (time available)"** to `config.yaml` defaults; pre-select it in the wizard when a `rushed` finding exists.
- In the viewer, show my 3 longest thinks of the game.

### F11 — Command-line report

So the engine logic can be tested before any UI work:

```
python -m core.review path/to/study.pgn [--chapter N] [--color white|black]
```

Prints, per chapter: decision points (candidates, engine top set, hit / chose-best), eval checks, line holes, blind spots, rushed moves, and the per-game metrics from F15. Exit code 0. No database writes unless `--save` is passed.

### F12 — Database changes

Keep using `ALTER TABLE … ADD COLUMN` / `CREATE TABLE IF NOT EXISTS` in `core/db.py` so existing data is untouched.

- `games`: add `source_key` (unique), `chapter_url`, `chapter_name`, `analysis_hash`, `user_color`.
- `blunders`: add `source` (`manual` | `engine`), `finding_id`, `time_spent_s`, `clock_remaining_s`.
- New `analysis_runs`: `id, game_id, run_at, engine_id, settings_json, analysis_hash`.
- New `decision_points`: `id, run_id, game_id, move_number, side, fen, played_san, otb_candidates_json, post_candidates_json, engine_top_json, candidates_known (bool), hit (bool|null), post_hit (bool|null), chose_best (bool|null), time_spent_s`.
- New `findings`: `id, run_id, game_id, type, path_san_json, move_number, side, fen, user_value, engine_value, best_move_san, pv_san, win_loss, hint_text, explanation, status (open|seen|logged|dismissed), blunder_id (nullable)`.
  - `type` ∈ `eval_wrong, missing_eval, glyph_mismatch, candidate_miss, chose_worse, line_break_own, line_break_opp, blind_spot, rushed`.
- New `engine_cache` (see F4).

### F13 — Review screen (read-only analysis viewer)

New screen `ui/review.py`, opened per game after the engine run (and later from a game list).

**Layout:**

- **Left:** board (reuse `core/board_render.py`; extend it to draw several arrows and circles in different colours — my `[%cal]` arrows, and the engine's best move once revealed). Orientation from my colour.
- **Centre:** move list showing mainline and variations as an indented tree, with my comments, glyphs and eval symbols. Moves with findings get a small marker. `otb` alternatives visually distinguished from post-game ones.
- **Right:** findings list for the game, grouped by check. Clicking a finding jumps the board and move list to that position.

**Navigation:** click any move to jump; ← / → step through the current line; ↑ / ↓ switch between sibling variations; Home / End. "Open in Lichess" button for the current position (existing deep link). No piece moving.

**Hints before answers:** each finding shows only `hint_text` at first, e.g.
- "Your line 29.Qe6 … has a hole at Black's 2nd move — look again."
- "Your candidates at move 8 didn't include the engine's top move."
- "You didn't give an eval at the end of this line. What's yours?" → buttons for the eval bands; after I pick, the engine's band is revealed and compared.

A **"Show answer"** button reveals best move, short PV (≤ 6 plies, SAN), engine eval, and draws the best-move arrow. Revealing sets the finding to `seen`.

**Per-game summary header:** the metrics from F15 for this game.

### F14 — Wizard pre-fill

The existing wizard (`ui/analyze.py`) gets its queue from the review instead of only from glyphs/comments:

- Queue = my mainline moves that have any of: a `?`/`??` glyph or comment (existing behaviour), a `candidate_miss` or `chose_worse` finding, or a `blind_spot` finding. Line-hole findings (F8) are analysis errors and are **not** queued; they live in `findings` and feed the metrics.
- Pre-fill:
  - `layer` from the F7 mapping (engine-based pre-fill **replaces** the LLM pre-fill when available; keep the LLM pre-fill only for moves with no engine signal).
  - Secondary theme "Rushed (time available)" when F10 says so.
  - Notes: the PGN comment (existing) plus a one-line engine summary ("Engine: best was Qe6 (+2.1); you played Rff1 (−3.4)").
- `step` (1–4), primary theme, one-sentence fix and training prescription stay **manual**. The engine can't reliably tell Step 1 from Step 4.
- Saving links the `blunders` row to the finding (`finding_id`, `source = 'engine'`) and sets the finding to `logged`.

### F15 — Analysis-skill metrics (Patterns dashboard)

Computed per game and shown as trends over time on the existing Patterns screen (new section "Analysis skill"):

| Metric | Definition |
|---|---|
| Candidate hit rate | decision points with known candidates where `hit` / all such decision points |
| Chose-best rate | decision points with ≥2 `otb` candidates where `chose_best` / all such |
| Post-game discovery rate | decision points where `post_hit` and not `hit` / decision points with known candidates |
| Eval accuracy | eval claims that are Match or Close / all eval claims checked |
| Missing evals | line ends without an eval |
| Line soundness | lines with no F8 break / all lines checked |
| Opponent-reply misses | count of `line_break_opp` (blunder-check failures in analysis) |
| Blind spots | count per game |
| Rushed mistakes | count of `rushed` |

Show small sample sizes honestly (e.g. "2 / 3") rather than percentages alone.

### F16 — LLM explanations (later phase, M5)

Only after M1–M4 have been used on real games.

- Button "Explain" on a revealed finding, and an "Answer my question" action for comments that contain a question (`?` at the end, or words like "why", "don't understand"). Example from the sample: *"I don't understand why taking with the d pawn is better (acc to SF)"*.
- **Prompt input (all computed, never inferred by the LLM):** FEN; an 8×8 text diagram; side to move; material balance; pieces attacked and undefended for both sides; available checks and captures; the opponent's threat (engine best move after a null move, where legal); engine PV and eval for the move played/assumed and for the best move; my comment.
- **Instructions to the model:** explain only using the facts provided; don't introduce moves not in the PVs; 2–4 sentences; plain language.
- Use the existing OpenAI-compatible client in `core/llm.py`, with a separate `EXPLAIN_MODEL` / `EXPLAIN_BASE_URL` in `.env`, so explanations can use a different model (e.g. an API model) from the pre-fill classification. Default: the existing Ollama endpoint on the Mac mini (16 GB, so models ~7–14B).
- Label explanations "AI explanation — may contain mistakes". Store in `findings.explanation`.
- No board images are sent to the model.

---

## 5. Configuration additions (`config.yaml` defaults)

```yaml
lichess_username: i_will_analyze_games
lichess_study_id: YYeDmlVd

engine:
  command: ["stockfish"]
  threads: 4
  hash_mb: 512
  depth: 20
  time_ms: null
  multipv: 3

review:
  candidate_window: 5          # win% points
  chose_window: 5
  line_break_threshold: 10
  blind_spot_threshold: 10
  blind_spot_max: 3
  rushed_seconds: 30
  rushed_clock_fraction: 0.5
  eval_bands: [0.5, 1.2, 2.5]  # pawns: = | +=  | ± | +-
```

`.env` additions: `LICHESS_TOKEN` (optional, read-only, only for private studies), `EXPLAIN_MODEL`, `EXPLAIN_BASE_URL` (M5).

All thresholds are first guesses and will be tuned after a few games. Expose them in the Settings screen.

---

## 6. Milestones and acceptance

**M1 — Parsing and import**
- F1 fixed with migration; F2 incremental import working against the sample PGN and a live study; F3 tree built.
- Unit tests in `tests/` (pytest) using `tests/fixtures/sample_study.pgn` (my two real chapters, no `otb` tags) plus small hand-written PGNs that cover: `otb` after and before a move, nested variations, `swindle`, missing evals, eval NAGs on mainline moves, multiple chapters, duplicate import, updated chapter.

**M2 — Engine checks + CLI**
- F4–F11. `python -m core.review tests/fixtures/sample_study.pgn` prints a sensible report for both chapters.
- Tests for the check logic use **stubbed engine results** (no Stockfish needed in tests); one optional integration test runs real Stockfish if found on PATH.

**M3 — Database + Review screen**
- F12 migrations run cleanly on the existing `blunders.db` (back it up first, automatically, to `blunders.db.bak-<date>`).
- F13 viewer: navigation, findings, hints → answers, eval-band prompt for missing evals.

**M4 — Wizard + metrics**
- F14 queue and pre-fill; F15 metrics on the Patterns screen.

**M5 — Explanations**
- F16.

**Definition of done for every milestone:** tests pass, the app still launches and the existing paste-PGN → wizard flow still works, README updated.

---

## 7. Edge cases

- Chapter with no variations → only blind spots, time use and glyph checks run.
- Variation starting at move 1, or on the very last move.
- Line ending in checkmate or stalemate (engine eval is exact; no "missing eval" finding).
- Same position reached by transposition in two lines → engine cache hit.
- Non-standard PGN from Chess.com (no `ChapterURL`, maybe no clocks) → falls back to `Site`/hash; time use skipped if no clocks.
- `TimeControl` missing or `-` → skip F10.
- My colour can't be determined → ask with the existing buttons.
- Engine unavailable → import and viewer still work; checks show "engine not available".
- Chapters that are still unfinished: they appear as "New" — I simply don't select them yet.

---

## 8. Reference: sample data

`tests/fixtures/sample_study.pgn` — two chapters from my "Played Games" study:

1. `i_will_analyze_games – cicuska` (I'm White, Albin Countergambit, 0-1). Decision points with variations at moves 5, 8, 12 and 29; opponent-turn variation at 7…Bxf3; eval NAGs on line ends ($15) and on the mainline (11…Nxe5 $17).
2. `bipulpattanaik4321 – i_will_analyze_games` (I'm Black, 0-1). Decision points with variations at moves 8, 10, 11, 12, 13, 16, 17 and 23; opponent-turn variation at 19.Bb5; a question in a comment at move 17; `$7` (only move) used inside a line.
