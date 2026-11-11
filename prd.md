# chess-patterns — product requirements

A desktop app for reviewing my own chess games: it checks my **hand analysis** with Stockfish, then lets me log and classify my mistakes so I can see patterns over time — in my game mistakes and in the quality of my analysis.

This document is the single source of truth for what the app does and why. It replaces the earlier `SPEC.md` (the original app) and the first PRD (the analysis-review extension). Sections marked **Built** describe the app as it is; **Decision** notes record choices made during development; **To do** lists what's left.

---

## 1. Background and goals

My workflow after a game:

1. Put the game into a Lichess study (all games go into **one** study, one chapter per game).
2. Analyse it by hand, **without an engine**: variations for moves I considered, an eval symbol (=, +=, ±, +-, …) at the end of lines, comments, arrows.
3. Only then use an engine — but not the usual full-game "blunder / mistake / inaccuracy" report, which isn't very helpful.

**Goals**

- Use Stockfish to check *my analysis* rather than the game, and find where my thinking went wrong.
- Log each real mistake with a structured classification (thinking step, seen or not, themes, fix, training prescription), based on [The 4 Questions Strong Players Ask on Every Move](https://lichess.org/@/MattyDPerrine/blog/the-4-questions-strong-players-ask-on-every-move-that-you-probably-skip/WaE0weYc).
- Show long-term patterns in both: game mistakes and analysis skill.

**Guiding principles**

- **The engine judges, the LLM only explains.** No LLM is ever asked to find moves or evaluate positions on its own.
- **Hints before answers.** Every finding first says *where* to look; the engine's answer is revealed only when I ask.
- **Focused, not exhaustive.** A short list of meaningful findings per game, never a move-by-move engine dump.

---

## 2. Status

| Milestone | Features | Status |
|---|---|---|
| Original app | Paste PGN → wizard, puzzles + LLM recommendation, Settings, Patterns charts | Built |
| M1 — Parsing and import | F1 ?/?? fix, F2 study import, F3 analysis tree | Built |
| M2 — Engine checks + CLI | F4 engine, F5–F10 checks, F11 command-line report | Built |
| M3 — Database + Review screen | F12 tables, F13 Review screen, Games list | Built |
| M4 — Wizard + metrics | F14 wizard pre-fill, F15 analysis-skill metrics | Built |
| M5 — Explanations | F16 LLM explanations | **To do** — only after M1–M4 have been used on real games |

**Other open items**

- **To do:** expose the `engine:` and `review:` settings and `lichess_username` / `lichess_study_id` in the Settings screen (today: edit `config.yaml`).
- **To do:** move the LLM system prompts out of `core/llm.py` into `core/prompts/` files (project rule: prompts live in separate files). Do this with M5.

---

## 3. Tech stack

| Concern | Choice |
|---|---|
| UI | CustomTkinter |
| Chess logic, PGN | python-chess |
| Board rendering | python-chess SVG → cairosvg → Pillow → CTkImage (cairo from Homebrew; `main.py` locates it — don't set `DYLD_LIBRARY_PATH`, it crashes the app) |
| Engine | Stockfish over UCI (`chess.engine`), local or over SSH |
| Database | SQLite (`blunders.db`), engine cache in a separate `engine_cache.db` |
| Config | `config.yaml` (pyyaml); secrets in `.env` (python-dotenv) |
| LLM | OpenAI-compatible client against an Ollama endpoint |
| Lichess | study export API (optional read-only token), public puzzle API |
| Charts | matplotlib (Patterns screen) |
| Tests | pytest (added with uv); engine logic tested with stubbed results |
| Packaging | uv, Python 3.11 |

---

## 4. Files

```
main.py                 entry point (finds cairo + Tcl/Tk, raises the window at start-up)
ui/home.py              Home: Check for new games, paste PGN, chapter list, nav
ui/flow.py              engine progress screen; import → engine → review → wizard
ui/review.py            Review screen
ui/games.py             Games list
ui/analyze.py           wizard
ui/patterns.py          Patterns: Analysis skill + wizard-entry charts
ui/settings.py          Settings (themes, prescriptions, theme map, missed-win thresholds)
core/pgn_parser.py      read_games(), flagged ?/??/$9 moves
core/analysis_tree.py   F3 analysis tree
core/game_keys.py       source_key, analysis_hash
core/study_import.py    F2 study download and New / Updated / Already imported
core/engine.py          F4 engine service, win%, cache
core/checks.py          F5–F10 checks + glyph check, per-game metrics
core/review.py          F11 CLI: python -m core.review <pgn> [--save]
core/review_store.py    F12 runs, decision points, findings
core/run_review.py      engine run for a stored game (used by the UI)
core/review_nav.py      Review-screen logic (navigation, move list, finding placement)
core/wizard_queue.py    F14 queue and pre-fill
core/skill_metrics.py   F15 metrics across games
core/migrate_f1.py      one-off ?/?? label fix for old wizard entries
core/db.py, config.py, board_render.py, llm.py, puzzles.py
scripts/bench_engine.py benchmark engine settings on my own positions
tests/                  pytest suite; fixtures/sample_study.pgn = two real chapters
```

---

## 5. Configuration

### `.env`

```env
OLLAMA_API_KEY=...
OLLAMA_MODEL=...                # optional: overrides llm.model in config.yaml
OLLAMA_BASE_URL=...             # optional: overrides llm.base_url
LICHESS_TOKEN=lip_...          # optional, read-only, scope study:read, for a private study
# M5: EXPLAIN_MODEL=..., EXPLAIN_BASE_URL=...
CHESS_PATTERNS_DB=...           # optional: use another database file (e.g. a scratch copy)
```

The LLM endpoint is the `llm:` section of `config.yaml` (default `http://mac-mini:11434/v1`, `gemma4:12b`, `timeout_s: 90`). LLM failures never block the app; the wizard shows the reason.

### `config.yaml` (defaults; missing keys are filled in from these)

```yaml
primary_themes: [Fork, Pin, Skewer, Back rank, Mating net, Discovered attack, Zwischenzug,
                 Piece activity, Pawn structure, King safety, Prophylaxis, Calculation error,
                 Endgame technique, Opening prep gap, ...]
secondary_themes: [None, Time pressure, Opening prep gap, Endgame technique, King safety,
                   Opponent surprise, Rushed (time available), ...]
training_prescriptions: [Tactics puzzles (general), Fork puzzles, Pin and skewer puzzles, ...]
lichess_theme_map: {Fork: fork, Pin: pin, ...}     # our theme -> Lichess puzzle angle
missed_win_threshold: 150     # centipawns, Chess.com-style missed-win detection from [%eval]
winning_threshold: 150

lichess_username: i_will_analyze_games
lichess_study_id: YYeDmlVd

engine:
  command: ["stockfish"]      # or ["ssh", "mac-mini.local", "/opt/homebrew/bin/stockfish"]
  threads: 7
  hash_mb: 512
  depth: 15
  time_ms: null               # set to use time per position instead of depth
  multipv: 3                  # used only where the checks need several lines
  cache_path: engine_cache.db

review:                       # win% points unless noted
  candidate_window: 5
  chose_window: 5
  line_break_threshold: 10
  blind_spot_threshold: 10
  blind_spot_max: 3
  rushed_seconds: 30
  rushed_clock_fraction: 0.5
  eval_bands: [0.5, 1.2, 2.5] # pawns: = | +=/=+ | ±/∓ | +-/-+
  glyph_good_window: 2        # ?, ??, ?! on a move within this of best = mismatch
  glyph_bad_threshold: 10     # !, !!, !? on a move losing this much = mismatch
  only_move_window: 5         # □ but another move within this of best = mismatch
```

All thresholds are configurable defaults and first guesses, to be tuned after more games. Choosing "Other…" for a theme in the wizard appends it to the list.

**Decision:** default depth is 15, not 20 — my analysis lines are 4–5 moves deep. Default threads 7 (profiling: ~30% faster per position than 4 on this 8-core Mac).

---

## 6. Study conventions (input contract)

Anything not following these must degrade gracefully, never crash.

| What | How I write it in Lichess | Meaning |
|---|---|---|
| In-game candidate | `otb` (any case, whole word) in the comment of a variation's **first move**, before or after the move | Considered **during the game** |
| Post-game idea | A variation without `otb` | Found afterwards: checked for eval and holes, not counted as an in-game candidate |
| Played move | The mainline move | Always an in-game candidate |
| My evaluation | Eval glyphs: `$10` =, `$13` unclear, `$14` +=, `$15` =+, `$16` ±, `$17` ∓, `$18` +-, `$19` -+ | My claim about the position after that move |
| Swindle line | `swindle` in any comment of the line | Eval check skipped for that line (and its sub-variations) |
| Move glyphs | `!` $1, `?` $2, `!!` $3, `??` $4, `!?` $5, `?!` $6, `□` $7 | My claim about the move's quality |
| Arrows / circles | `[%cal …]`, `[%csl …]` | Shown on the board; not judged |
| Clock | `[%clk h:mm:ss]` on mainline moves | Time use (F10) |

Older chapters have no `otb` tags: their candidate statistics are "unknown", never misses.

---

## 7. Flow and screens (Built)

1. **Home.** **⟳ Check for new games** downloads the whole study (`GET https://lichess.org/api/study/{id}.pgn?clocks=true&comments=true&variations=true`, bearer token if set) off the UI thread. Or paste PGN (one game or a whole-study export) and click **Analyse →**. One game goes straight on; several show the chapter list: **New** (ticked), **Updated** (shown, not ticked), **Already imported** (behind "Show all"). My colour comes from `lichess_username`; if it can't be detected, I pick White/Black per chapter (single paste: the White/Black buttons).
2. **Engine progress.** Stockfish checks the chapter on a worker thread with a progress bar; **Skip engine →** stops it. If the engine is missing the review still opens with "Engine not available".
3. **Review screen** (F13).
4. **Wizard** for the chapter's queue (F14), then the next chapter.
5. **📋 Games** lists every imported game with open findings; **Review →** opens it (the engine runs only if the game was never analysed or its analysis changed; **⟳ Re-run engine** forces it); **Wizard →** appears when moves wait.
6. **📊 Patterns** (F15 + wizard-entry charts), **⚙ Settings**.

**Decision:** games without `?`/`??` moves are still imported and reviewed (the wizard is just skipped) — previously the paste flow stopped with "No annotated moves found".

---

## 8. Features

### F1 — ?/?? NAG fix (Built)

`$2` = `?` = mistake, `$4` = `??` = blunder (python-chess `NAG_MISTAKE` / `NAG_BLUNDER`); they had been swapped. `python -m core.migrate_f1` lists rows whose `flag_type` disagrees with the glyph re-read from `games.pgn_raw` (move number + side + SAN); `--apply` backs up first and changes only `flag_type`; rows it can't match are left alone. Sample: 8.Be2 → mistake, 29.Rff1 → blunder.

**Decision:** the database had been cleared before M1 and was not restored, so there were no old rows to migrate.

### F2 — Study import with incremental sync (Built)

- De-duplication key `games.source_key` (unique): `chapter:<ChapterURL>`, else `site:<Site>` if Site is a real game URL (not "Chess.com"), else `game:<GameId>`, else `moves:<sha256 of mainline SAN>`.
- `games.analysis_hash`: SHA-256 of the move text (variations, comments, NAGs, arrows) with headers, `[%clk]`, `[%eval]`, `[%emt]` removed and whitespace normalised — so a pasted chapter and the API export of the same chapter match, and clock-only changes don't count.
- Importing an **Updated** chapter replaces that game's `pgn_raw` and hash in place (same `games.id`); wizard entries are never touched. Re-pasting an imported game reuses its row.

### F3 — Analysis tree (Built)

`core/analysis_tree.py` turns a chapter into nodes (path, FENs, side, mine or not, glyphs, eval NAG, cleaned comments, `otb`, `swindle`, arrows/circles, clock), **decision points** (mainline, my move, ≥1 sibling variation: played move, `otb` and post-game alternatives) and **analysis lines** (every variation incl. nested, with branch point, depth and swindle flag), read from my colour.

### F4 — Engine service (Built)

`core/engine.py`: any UCI command; scores stored from White's view and as win% (Lichess formula `50 + 50·(2/(1+e^(−0.00368208·cp)) − 1)`, mates → 0/100). Cache keyed by position (EPD, so transpositions share entries), limit, MultiPV and engine name. Clear "Stockfish not found — set engine.command in config.yaml". Progress callback; runs off the UI thread.

**Decisions:**
- Cache lives in its own git-ignored `engine_cache.db` (not `blunders.db`), so it never needs a backup and can be deleted any time.
- MultiPV is ~5× slower per search, and only decision points and only-move-glyph positions need more than one line, so only those get `multipv`; everything else MultiPV 1. A cached MultiPV result also serves a MultiPV-1 request. (Sample study: 601 s → 209 s from an empty cache; app overhead negligible — see `scripts/bench_engine.py`.)
- With several threads Stockfish isn't deterministic: evals move by ~0.1–0.5 pawns between runs, so findings near a threshold can flip.

### F5 — Is my evaluation right? (Built)

Every eval NAG (mainline or variation) and every line end. Bands from `eval_bands` (White's view). **Match** = same band; **Close** = adjacent band on the same side (incl. `=` vs `+=`), shown as info; **Wrong** = 2+ bands apart or opposite sides → finding `eval_wrong`. `$13` unclear: no verdict, engine band shown. Line end without an eval → `missing_eval` (in the viewer I pick a band before seeing the engine's). Swindle lines skipped; lines ending in mate/stalemate need no eval.

**Move-glyph check (Built):** on my own moves — `?`/`??`/`?!` but within `glyph_good_window` of best; `!`/`!!`/`!?` but losing `glyph_bad_threshold`; `□` but another move within `only_move_window` (or the move loses) → `glyph_mismatch`.

### F6 — Did my in-game candidates include the engine's best? (Built)

At each decision point: engine top set = best move + at most one more within `candidate_window`. **Hit** if any `otb` candidate (incl. the played move) is in the top set, or leads to a position within `candidate_window` win% of the best move (so near-best moves are never a miss or a "rushed mistake"); **post-game hit** if any untagged alternative is. No `otb` tags → candidates unknown (no finding), post-game hit still computed. Miss with known candidates → `candidate_miss`.

### F7 — Did I pick the best of my candidates? (Built)

With ≥2 `otb` candidates: each is evaluated; **chose best** if the played move is within `chose_window` of the best candidate, else `chose_worse` ("You considered X, which was better…"). Wizard layer mapping: candidate miss → `didnt_see`; considered but played worse → `got_it_wrong`; played the best → none.

### F8 — Holes in my lines (Built)

Every line, from its **second** move: loss = engine's best win% in the position before − win% after the line's move (mover's view). First move losing ≥ `line_break_threshold` → `line_break_own` (my move) or `line_break_opp` (assumed a weaker reply — the blunder-check failure). Only the first break per line.

### F9 — Blind spots (Built)

My mainline moves with no variation at them, no glyph or eval symbol, no comment and no arrows, losing ≥ `blind_spot_threshold`; at most `blind_spot_max`, largest first.

### F10 — Time use (Built)

From `[%clk]` + `TimeControl` (`900+10`; missing, `-` or correspondence → skipped). Time spent = previous own clock − clock + increment (first move: base − clock). `time_spent_s` / `clock_remaining_s` go on mainline findings and wizard entries. `rushed`: a flagged move (?/??, blind spot, chose_worse, candidate_miss) played in < `rushed_seconds` while the clock *before* the move was > `rushed_clock_fraction` × base. Example: 29.Rff1 took 22 s with 13:44 on the clock. The viewer shows my 3 longest thinks.

### F11 — Command-line report (Built)

`python -m core.review <pgn> [--chapter N] [--color white|black] [--depth D | --time-ms T] [--save]`: decision points, eval checks, line holes, blind spots, glyph check, time use, metrics. Exit 0 (2 if the file or engine is unavailable). No database writes unless `--save` (imports chapters if needed, then stores the run).

### F12 — Database (Built)

Migrations only `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE … ADD COLUMN`; `blunders.db` is copied to `blunders.db.bak-<YYYYMMDD-HHMMSS>` before any schema change or backfill.

```
games            id, logged_at, white, black, result, time_control, played_at, pgn_raw,
                 source_key (unique), chapter_url, chapter_name, analysis_hash, user_color
blunders         id, game_id, logged_at, move_number, move_side, move_san, fen, lichess_url,
                 flag_type, annotation, step, layer, diagnosis, primary_theme, secondary_theme,
                 one_sentence_fix, training_prescription, puzzle_urls, llm_recommendation, notes,
                 source ('manual'|'engine'), finding_id, time_spent_s, clock_remaining_s
analysis_runs    id, game_id, run_at, engine_id, settings_json, analysis_hash,
                 metrics_json, move_evals_json
decision_points  id, run_id, game_id, move_number, side, fen, played_san, path_san_json,
                 otb_candidates_json, post_candidates_json, engine_top_json, candidates_known,
                 hit, post_hit, chose_best, layer_prefill, time_spent_s
findings         id, run_id, game_id, type, path_san_json, move_number, side, fen, user_value,
                 engine_value, best_move_san, pv_san, win_loss, hint_text, answer_text,
                 explanation, status ('open'|'seen'|'logged'|'dismissed'), blunder_id,
                 time_spent_s, clock_remaining_s, updated_at
engine_cache     (in engine_cache.db) key, fen, depth, time_ms, multipv, engine_id,
                 result_json, created_at
```

`flag_type` is `blunder` / `mistake` / `missed_win`, or the engine reason (`candidate_miss`, `chose_worse`, `blind_spot`) for moves queued only by the engine. Finding types: `eval_wrong, missing_eval, glyph_mismatch, candidate_miss, chose_worse, line_break_own, line_break_opp, blind_spot, rushed`.

**Re-runs (Decision):** a finding that appears again (same type, same move path) keeps its row — id, status, my eval-band answer, wizard link — with fresh engine data; open/seen/dismissed findings that no longer appear are removed; logged findings are never deleted.

### F13 — Review screen (Built)

- **Board:** my colour at the bottom; my `[%cal]`/`[%csl]` drawings; last move; the engine's best move in purple once an answer is revealed.
- **Move list (Lichess style):** mainline as rows (number | White | Black, striped); a mainline move's comment as its own block and its alternatives as shaded lines below (├ / └ for several), deeper sub-variations inline in lighter parentheses; "…" when White's move is interrupted; figurines and coloured glyphs; `otb` lines green, post-game ideas blue; ● on moves with findings; click to jump.
- **Choice quiz:** an unrevealed `chose_worse` card shows one button per move I considered (played move + `otb` siblings). My pick is stored in `findings.user_answer`; the answer opens with "✓ Right …" / "✗ You picked …". "Show answer" still skips.
- **Findings:** grouped (Your candidates · Evaluations · Holes in your lines · Blind spots · Time · Your glyphs). Hint first; **Show answer** reveals best move, eval and line (≤ 6 plies) and marks it `seen`. Missing evals: pick a band first, then see the engine's and the verdict. **Dismiss / Restore** (`dismissed` findings are hidden behind "show dismissed" and left out of metrics; logged ones can't be dismissed).
- **Header:** per-game metrics as small counts; longest thinks under the board.
- **Keys:** ← → current line, ↑ ↓ sibling variations, Home / End. **Open in Lichess ↗** for the current position. No piece moving.

### F14 — Wizard queue and pre-fill (Built)

- **Queue:** my mainline moves with a `?`/`??` glyph (or `$9` / eval-swing missed win, as before), or a non-dismissed `candidate_miss`, `chose_worse` or `blind_spot`. Line holes don't queue. Moves already saved in the wizard for this game are skipped.
- **Pre-fill — facts:** layer from F7; "Rushed (time available)" when a `rushed` finding exists (never overridden); notes = my comment + "Engine: best was Qe6 (+2.10); you played Rff1 (-3.40)."
- **Pre-fill — engine guesses** (`core/position_facts.py`): from the board and the engine (best line, played move, opponent's best reply, null-move threat) it finds tactics (fork, pin, skewer, discovered attack, mate / back-rank mate, winning an unprotected piece) and loose pieces. Step: my move allowed a tactic that was already threatened → 1; allowed a new one → 4 (2 if I also missed a real tactic of my own); best move was my own check/tactic → 2; else 3. Theme from the relevant line's tactic; prescription from the theme, else "Play slower time controls" if rushed, else by step.
- **Pre-fill — AI** (`core/prefill.py`, prompt `core/prompts/wizard_prefill.md`): one structured-output call per move with the facts, guesses, my comment and considered moves; returns step, layer, both themes, prescription (enums from config) and a one-sentence fix. It may change the guesses (marked "AI suggestion"); values equal to the guesses stay "from engine".
- **Wizard:** suggestions for the whole queue are computed by a background job (`core/prefetch.py`, one per game, engine via `run_review.open_engine`) that the Review screen starts as soon as it opens when the wizard follows; the wizard reuses the job if the queue is unchanged (else restarts it) and applies results on the UI thread; fields show their source; a field I edit is never overwritten; engine/LLM problems appear as an orange line and the other source still fills in.
- **Save:** stores `source`, `finding_id` (main finding), time spent / clock left; all of the move's findings become `logged` with `blunder_id`.

**Decisions:** comment-only moves don't queue (SPEC/PRD said "or comment", but the code never did and my studies comment many ordinary moves); already-saved moves are skipped.

### F15 — Analysis-skill metrics (Built)

On Patterns ("Analysis skill"), per game from the latest run and summed across games as x / y: candidate hit rate, chose-best rate, post-game discovery rate, eval accuracy (match or close), missing evals, line soundness, opponent-reply misses, blind spots, rushed mistakes. Dismissed findings count as passes. Totals + latest game; trend charts from two games on.

### F16 — LLM explanations (To do, M5)

- "Explain" on a revealed finding, and "Answer my question" for comments that ask one (`?` at the end, "why", "don't understand"; e.g. *"I don't understand why taking with the d pawn is better (acc to SF)"*).
- **Prompt input, all computed** (already built for the wizard: `core/position_facts.py`, `PositionFacts.to_text()`): FEN; 8×8 text diagram; side to move; material; attacked and undefended pieces for both sides; available checks and captures; the opponent's threat (engine best after a null move, where legal); engine PV and eval for the move played/assumed and for the best move; my comment.
- **Model instructions:** use only the facts given; no moves outside the PVs; 2–4 sentences; plain language.
- Same OpenAI-compatible client with separate `EXPLAIN_MODEL` / `EXPLAIN_BASE_URL` (default: the Ollama endpoint on the Mac mini, 16 GB → ~7–14B models). Label "AI explanation — may contain mistakes". Store in `findings.explanation`. No board images.

---

## 9. Wizard (original app, Built)

For each queued move: board (from-square green, to-square red), "Move 23 · Black · Blunder", Open in Lichess, my comment, progress ("2 of 3"). Fields:

| # | Field | Widget |
|---|---|---|
| 1 | Thinking step | Step 1 – missed opponent threat / Step 2 – missed own tactic / Step 3 – wrong plan / Step 4 – no blunder check |
| 2 | Did you see it? | "Didn't see it" / "Saw it, got it wrong" |
| 3 | Diagnosis | generated from step × layer (below) |
| 4 | Primary theme | from config, with "Other…" |
| 5 | Secondary theme | from config, with "None" and "Other…" |
| 6 | One-sentence fix | text |
| 7 | Training prescription | from config |
| 8 | Notes | pre-filled (comment + engine line) |

**Skip** or **Save → next**. On save: write the row; in the background fetch 3–5 Lichess puzzles for the theme (`/api/puzzle/next?angle=…` via `lichess_theme_map`) and an LLM recommendation; show them when ready. The last saved move's puzzles and recommendation stay in a box under the board (labelled with the move) while the wizard moves on; the worker thread never touches Tk, the UI thread polls for its result.

**Defaults are not choices:** Thinking step and Primary theme start on "— choose —"; engine/AI suggestions fill them, otherwise Save asks for a choice (as it does for "Did you see it?"). **Theme → puzzle:** `lichess_theme_map` maps themes to Lichess puzzle themes (e.g. 3-ply calculation, Calculation error, Calculation → `mateIn2`; the old separate "3-ply" theme is merged into "3-ply calculation", in config and in saved entries; Hanging Piece/Pawn → `hangingPiece`; Evaluation → `advantage`). With no mapping for the primary theme, the secondary theme's is used; with none, the results box says so. Adding a theme through "Other…" also offers a Lichess puzzle theme dropdown (default "none"). The **Patterns** screen ends with a **Training** section: the latest 20 entries with move, theme, one-sentence fix, recommendation ("No recommendation yet" if empty) and clickable puzzle links.

| Step | Didn't see it | Saw it, got it wrong |
|---|---|---|
| 1 | Scanning gap — you're not pausing to read your opponent's move | Defensive misjudgement — you saw the threat but chose the wrong response |
| 2 | Pattern recognition gap — you're not scanning for your own tactics | Calculation error — you found the idea but miscalculated the line |
| 3 | Positional knowledge gap — the right plan wasn't visible to you | Evaluation error — you saw the plans but chose the inferior one |
| 4 | Habit gap — you skipped the blunder check entirely | Calculation under pressure — blunder check ran but missed their best reply |

**LLM calls** (`core/llm.py`, OpenAI client against the Ollama endpoint):

- *Pre-fill* — system prompt: classify the player's annotation of their own mistake into thinking step (1–4) and layer (`didnt_see` / `got_it_wrong`); reply only with JSON like `{"step": 2, "layer": "didnt_see"}`. Input: the comment.
- *Recommendation* — system prompt: 3–5 sentences on what pattern to train, why the puzzles address the blind spot, and one concrete tip; don't repeat the classification. Input: JSON of the classification.

The Patterns screen's wizard-entry charts: blunders by step, top themes, step × layer heatmap, training prescriptions, monthly trend by step, summary stats.

---

## 10. Edge cases (all handled)

- PGN that can't be parsed, empty chapters, unknown NAGs/comments → message or ignored, never a crash.
- Chapter with no variations → only blind spots, time use and glyph checks.
- Variation at move 1 or on the last move; lines ending in mate/stalemate (exact eval, no missing-eval finding); transpositions (cache hit).
- Chess.com PGN (no ChapterURL, maybe no clocks) → move-hash key; time use skipped without clocks; `TimeControl` missing or `-` → F10 skipped.
- Colour can't be determined → pick it (per chapter / White-Black buttons).
- Engine unavailable → import, viewer and wizard still work; review shows "Engine not available".
- Unfinished chapters show as New — just don't tick them.
- LLM or Lichess puzzle API down → wizard still works; "Recommendation unavailable".
- `config.yaml` / `blunders.db` missing → created with defaults.
- "Other…" theme left empty → inline validation message.

---

## 11. Out of scope

- Writing anything back to Lichess (no study write access).
- Judging my **opponent's actual game moves** (opponent moves inside my analysis lines are checked — F8).
- Automatic tactic naming — I pick the theme.
- Opening repertoire detection.
- Board images to an LLM / vision models; chess-specific models such as Queen.
- An interactive board for moving pieces (viewer is read-only; "Open in Lichess" covers exploration).
- A full-game engine report or accuracy score.
- User accounts / multi-user; cloud sync of the database.

## 12. Future ideas

- Review mode: old mistakes as spaced-repetition flashcards.
- Link Patterns data points back to their positions.
- Settings screen for engine / review thresholds (see Status).

## 13. Testing

`uv run pytest` (≈180 tests): sample study + hand-written PGNs; engine checks with stubbed results; a fake UCI engine for the engine service and UI flows; Tk smoke tests in a hidden window (one shared root — a second root hangs Tk on macOS); two short real-Stockfish tests if it's installed; `uv run pytest -m network` for the live Lichess study.
