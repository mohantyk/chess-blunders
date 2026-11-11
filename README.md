# chess-patterns

A desktop app for logging, classifying, and analysing chess blunders and mistakes, with the goal of identifying long-term patterns and generating targeted training recommendations.

Based on: [The 4 Questions Strong Players Ask on Every Move That You Probably Skip](https://lichess.org/@/MattyDPerrine/blog/the-4-questions-strong-players-ask-on-every-move-that-you-probably-skip/WaE0weYc)

---

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Cairo graphics library (for board rendering)

---

## Setup

### 1. Install Cairo

Cairo is a C graphics library required for rendering chess board images. It is not a Python package and must be installed separately.

**macOS:**
```bash
brew install cairo
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt install libcairo2
```

**Windows:** Download and install the [GTK3 runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases), which bundles Cairo.

---

> **macOS:** you don't need to set `DYLD_LIBRARY_PATH`. `main.py` finds Homebrew's Cairo on its own. Setting it in your shell (or on the command line) makes macOS load Homebrew's copies of other libraries in place of Python's own, and the app crashes on start with "Bus error". If you added it to `~/.zshrc` or `~/.bash_profile` earlier, remove that line.

### 2. Install Python dependencies

```bash
uv venv
source .venv/bin/activate
uv sync
```

---

### 3. Configure environment variables

Copy the example below into a file named `.env` in the project root and fill in your values:

```env
OLLAMA_API_KEY=your_key_here          # any value works for a local Ollama
# OLLAMA_BASE_URL=http://mac-mini:11434/v1   # optional: overrides llm.base_url in config.yaml
# OLLAMA_MODEL=gemma4:12b                    # optional: overrides llm.model
```

The LLM endpoint and model are set in the `llm:` section of `config.yaml` (default: the Ollama server on the Mac mini, `http://mac-mini:11434/v1`, model `gemma4:12b`); the env vars above override them. The LLM fills in the wizard and writes the training recommendation. If it can't be reached, the app still works and the wizard says why (e.g. "AI suggestions unavailable: can't reach http://mac-mini:11434/v1").

**Lichess token (only for a private study).** "Check for new games" downloads your study from Lichess. If the study is private, add a read-only token:

1. Open <https://lichess.org/account/oauth/token/create?scopes[]=study:read&description=chess-patterns>. Only **Read private studies and broadcasts** should be ticked.
2. Click **Create** and add the token to `.env`:

```env
LICHESS_TOKEN=lip_...
```

The app never writes to Lichess, so no other scope is needed.

### 3b. Set your Lichess username and study

In `config.yaml`:

```yaml
lichess_username: i_will_analyze_games   # used to work out which colour you played
lichess_study_id: YYeDmlVd               # the study all your games go into (ID or URL)
```

---

### 4. Run the app

```bash
source .venv/bin/activate
python main.py
```

---

## Getting started

This section walks a new user through a full session from first launch to reviewing patterns.

### Step 1 — Get your games in

**Option A — sync your study (recommended).** Put each game in your Lichess study (one chapter per game) and analyse it there. Then click **⟳ Check for new games** on the home screen. The app downloads the whole study and lists every chapter:

| Status | Meaning | Ticked by default? |
|---|---|---|
| **New** | Not imported yet | Yes |
| **Updated** | Imported before, but you've changed the analysis since (new variations, comments, glyphs or arrows; clock changes don't count) | No |
| **Already imported** | Nothing changed. Hidden until you tick **Show all** | No |

Your colour is detected from `lichess_username`. If it can't be, pick White/Black on that row. Click **Import & analyse selected →** and the wizard runs on each ticked chapter in turn. Re-importing an updated chapter replaces the stored PGN; wizard entries you already saved are never changed.

**Option B — paste a PGN.** Follow the steps below. Pasting a whole-study export (several chapters) shows the same chapter list as Option A.

#### Exporting a single game from Lichess

Open the game you want to review on Lichess. Before exporting:

- Annotate it first: mark your mistakes with "?" / "??", add variations (tag in-game candidates with `otb`), eval symbols and comments.
- Click **Share & export → Export PGN**, and tick **Include annotations**.
- Copy the full PGN text to your clipboard.

> Every imported game gets an engine review of your analysis. The wizard then takes your "?" (mistake) and "??" (blunder) moves, plus moves the engine flags (missed candidates, worse choices, blind spots). Comments go into the wizard notes, but don't put a move in the wizard on their own.

---

### Step 2 — Import the PGN

1. Launch the app: `python main.py`
2. Paste your PGN into the large text area on the home screen.
3. Click **White** or **Black** to indicate which side you played. The app picks it for you if your `lichess_username` is in the game's headers.
4. Click **Analyse →**.

Pasting a game that's already in the database reuses it rather than adding a duplicate.

The app parses the PGN, extracts your flagged moves, and launches the review wizard.

---

### Step 3 — Review your analysis

After import, each chapter is checked by Stockfish (a progress bar shows how far it's got; **Skip engine →** stops it), then the **Review** screen opens:

- **Board (left):** the position, your Lichess arrows and circles, and the last move. Once you reveal an answer, the engine's move is drawn in purple.
- **Move list (centre):** laid out like Lichess. The main line is a table (move number, White, Black). A move's comment appears as its own paragraph under it, and its variations as shaded lines below (├ / └ when there are several), with deeper side-lines in lighter brackets. Pieces are shown as figurines (♘f4+), glyphs in colour. Lines tagged `otb` are green, post-game ideas blue, and moves with a finding are marked ●. Click a move to jump to it.
- **Findings (right):** grouped by check. Each finding shows a **hint** first (where to look). Click **Show answer** for the engine's move, line and eval. For a line end where you didn't give an eval, you pick your own first (`+-` … `-+`), then see the engine's. When you played the worse of your candidates, the card asks which was best and shows a button per move you considered; your pick is saved and the answer says if you were right. **Dismiss** hides a finding you disagree with and leaves it out of the metrics.
- **Header:** the game's analysis-skill metrics, shown as small counts like "2/3", not just percentages.
- **Keys:** ← → step through the current line, ↑ ↓ switch between variations, Home / End jump to the start / end. **Open in Lichess ↗** opens the current position.

**Continue to wizard →** then goes on to the wizard below. Games without `?`/`??` moves skip the wizard.

Re-open any game later from **📋 Games** on the home screen. The engine only runs again if the chapter's analysis changed. Use **⟳ Re-run engine** to force it, for example after changing settings. On a re-run, findings you've already seen, dismissed or logged keep their status.

### Step 4 — Work through the review wizard

**Which moves come up:**
- your moves marked `?` or `??`;
- moves where the engine found something about the move itself: your in-game candidates missed its best move, you picked the worse of your candidates, or an unannotated move cost a lot (a blind spot).

Holes in your analysis lines aren't game mistakes, so they stay on the Review screen and in the metrics. Moves you've already saved in the wizard don't come up again, and neither do findings you dismissed.

**What's filled in for you** (you can change it all). The work starts in the background as soon as the Review screen opens, so while you read the findings the suggestions are being prepared and the wizard usually opens with them ready:
- **Facts from the engine:** "Didn't see it" if the engine's best wasn't among your `otb` candidates, "Saw it, got it wrong" if you considered it and played something worse; "Rushed (time available)" as secondary theme when you played quickly with plenty of time left. These are never changed by the AI.
- **Engine guesses:** the engine looks at the position: was the best move your own check or tactic (fork, pin, skewer, discovered attack, mate, a free piece)? Did your move allow such a tactic, and was that threat already there before your move? From that it guesses the **thinking step**, the **primary theme** and the **training prescription**.
- **AI suggestions:** the LLM gets those facts, your comment and the moves you considered, and fills in every field, including a **one-sentence fix**. It keeps the engine's guesses unless your comment points elsewhere.
- **Notes:** your comment plus an engine line, e.g. "Engine: best was Qe6 (+2.10); you played Rff1 (-3.40)."

A small grey label next to each field says where its value came from: "· from engine", "· AI suggestion (model)", or "suggesting…" while it's still working. Once you change a field, it's yours: later suggestions won't touch it. If the engine or the LLM can't be reached, an orange line at the top of the form says why, and the rest is still filled in. Saving also records the time you spent and the clock left, and links the entry to the engine finding.

For each flagged move you will see:

- The **board position** at the moment of the mistake, with the move number, side, and flag type shown above it.
- A link to **Open in Lichess ↗** if you want to explore the position in the engine.
- The **original annotation or comment** from the PGN.

Fill in the eight fields on the right:

| # | Field | What to enter |
|---|-------|---------------|
| 1 | **Thinking step** | Which step in your calculation process broke down — e.g. candidate generation, evaluation, blunder-check |
| 2 | **Did you see it?** | Whether you missed the idea entirely, or saw it but reasoned incorrectly |
| 3 | **Diagnosis** | Auto-filled once you complete steps 1 and 2 |
| 4 | **Primary theme** | The main tactical or positional theme (e.g. pin, outpost, king safety) |
| 5 | **Secondary theme** | An optional second theme |
| 6 | **One-sentence fix** | What you would do differently next time |
| 7 | **Training prescription** | The type of study that would address this gap (e.g. tactics puzzles, endgame drills) |
| 8 | **Notes** | Any freeform observations (optional) |

Click **Save → next** to log the blunder and move to the next one, or **Skip** to skip without saving.

Thinking step and Primary theme start on "— choose —" unless the engine or AI filled them; Save asks you to choose. If you add a theme with "Other…", you can also pick a Lichess puzzle theme for it (default "none").

After saving, the app automatically fetches relevant Lichess puzzles and (if configured) an LLM recommendation for targeted training. The result stays visible under the board, labelled with the move, while you continue. After the last move, the wizard ends on a **training page** listing every move you saved in that game with its fix, recommendation and clickable puzzle links (moves still being fetched say so and fill in when ready); its button continues to the next chapter or back home. Everything is also kept on the **Patterns** screen. Themes map to puzzles via `lichess_theme_map` in `config.yaml` (calculation themes such as "3-ply calculation" lead to mate-in-2 puzzles; if the primary theme has no mapping, the secondary theme's is used).

---

### Step 5 — Review your patterns

Once you have logged several games, click **📊 Patterns** on the home screen to open the patterns dashboard.

At the top, **Analysis skill** shows how good your own analysis is, across all games checked by the engine and for the latest game:
- candidate hit rate, chose-best rate and post-game discovery rate;
- eval accuracy, missing evals and line soundness;
- opponent-reply misses, blind spots and rushed mistakes.

Totals are shown as counts like "3 / 7", so small samples stay honest. With two or more games you also get trend charts. Dismissed findings count as if the check had passed.

The wizard-entry charts below show:

- **Thinking step breakdown** — which step fails most often
- **Theme frequency** — your most common mistake themes
- **Move heatmap** — which squares and move numbers you blunder on most
- **Training prescriptions** — what your logged entries suggest you should study
- **Monthly trend** — how your blunder rate is changing over time
- **Training** — your latest 20 entries with the fix, the AI recommendation and clickable Lichess puzzle links

---

### Step 6 — Adjust settings

Click **⚙ Settings** on the home screen to edit:

- the primary and secondary themes and training prescriptions shown in the wizard;
- the map from your themes to Lichess puzzle themes;
- the missed-win thresholds.

Changes are saved to `config.yaml` immediately. The engine and review settings (`engine:` and `review:`) and your Lichess username/study aren't in the Settings screen yet: edit them in `config.yaml`. The LLM endpoint and model are in the `llm:` section of `config.yaml` (or `.env`, which overrides it).

---

## Usage summary

1. Analyse the game by hand in your Lichess study: variations (`otb` for in-game candidates), eval symbols, "?" / "??", comments.
2. Click **⟳ Check for new games** (or paste a PGN and click **Analyse →**). Tick the chapters to import.
3. Stockfish checks your analysis, then the **Review** screen opens. Work through the findings: hint first, then **Show answer**.
4. **Continue to wizard →**: classify each queued move (thinking step, seen or not, themes, fix, prescription). Every field is pre-filled from the engine and the LLM; change whatever you disagree with.
5. After saving, the app fetches targeted Lichess puzzles and an LLM recommendation.
6. Re-open any game from **📋 Games**. Watch your trends on **📊 Patterns**.

---

## File structure

```
chess-patterns/
├── main.py               # app entry point
├── ui/
│   ├── home.py           # home / PGN import screen
│   ├── review.py         # Review screen: board, move tree, findings (hint → answer)
│   ├── flow.py           # engine progress screen; import → engine → review → wizard
│   ├── games.py          # list of imported games
│   ├── analyze.py        # wizard screen
│   ├── patterns.py       # patterns dashboard: analysis skill + wizard-entry charts
│   └── settings.py       # editable config screen
├── core/
│   ├── analysis_tree.py  # study chapter → moves, variations, otb/swindle tags, evals, arrows, clocks
│   ├── study_import.py   # Lichess study download + New / Updated / Already imported
│   ├── game_keys.py      # source_key (de-duplication) and analysis_hash (change detection)
│   ├── migrate_f1.py     # one-off fix for mistake/blunder labels saved before the ?/?? fix
│   ├── engine.py         # Stockfish service: win% scores, cache, progress
│   ├── checks.py         # engine checks on your analysis (evals, candidates, holes, blind spots, time)
│   ├── review.py         # command-line report: python -m core.review <pgn>
│   ├── review_store.py   # engine runs, decision points and findings in blunders.db
│   ├── review_nav.py     # Review-screen logic: navigation, move list, finding placement
│   ├── run_review.py     # run the engine checks on a stored game (used by the UI)
│   ├── wizard_queue.py   # wizard queue from glyphs and engine findings
│   ├── position_facts.py # engine facts about a move (tactics, threats) + rule guesses
│   ├── prefill.py        # wizard pre-fill: engine facts + rule guesses + one LLM call
│   ├── prefetch.py       # background pre-fill job per game, started from the Review screen
│   ├── prompts/          # LLM system prompts (wizard_prefill.md, recommendation.md)
│   ├── skill_metrics.py  # analysis-skill metrics across games (Patterns screen)
│   ├── pgn_parser.py     # PGN parsing and blunder flagging
│   ├── db.py             # SQLite read/write
│   ├── config.py         # config.yaml loading and saving
│   ├── board_render.py   # FEN → board image pipeline
│   ├── llm.py            # LLM client (Mac mini Ollama by default): JSON answers, recommendations
│   └── puzzles.py        # Lichess puzzle API
├── scripts/
│   └── bench_engine.py   # benchmark engine settings on your own positions
├── config.yaml           # theme lists and settings (edit here or in-app)
├── prd.md                # product requirements: what the app does and why
├── tests/                # pytest suite (fixtures/sample_study.pgn = two real study chapters)
├── blunders.db           # SQLite database (auto-created on first run)
├── .env                  # secrets — never commit this file
└── requirements.txt
```

---

## Checking your analysis with Stockfish (command line)

The engine checks your **own analysis**, not the game. It looks at:

- **your evaluations:** do your `=`, `+=`, `±`, `+-` symbols match the engine's?
- **your in-game candidates:** did the moves you tagged `otb` include the engine's best, and did you pick the best of them?
- **holes in your lines:** a move inside one of your variations that's a mistake, especially a weak reply you assumed for the opponent.
- **blind spots:** costly moves you didn't annotate at all.
- **time use:** mistakes played fast while you still had plenty of time.

```bash
brew install stockfish                      # once
python -m core.review tests/fixtures/sample_study.pgn
python -m core.review my_study.pgn --chapter 3 --color black --depth 16
python -m core.review my_study.pgn --save   # also store the findings for the Review screen
```

**Study conventions** the checks rely on:

| What | How |
|---|---|
| In-game candidate | Write `otb` in the comment of a variation's first move |
| My evaluation | Lichess eval glyphs `=` `+=` `=+` `±` `∓` `+-` `-+` (and `∞` for unclear) |
| Swindle line | Write `swindle` in a comment; its eval isn't judged |

Chapters without `otb` tags show in-game candidate stats as "unknown" rather than misses.

**Engine settings** (`engine:` in `config.yaml`): `command` (default `["stockfish"]`; to use the Mac mini, `["ssh", "mac-mini.local", "/opt/homebrew/bin/stockfish"]`), `threads`, `hash_mb`, `depth` or `time_ms`, `multipv`.

Results are cached in `engine_cache.db` (not in git), so re-running a chapter is fast. Deleting the cache file is always safe.

**Thresholds** (`review:` in `config.yaml`) are first guesses; tune them to taste:

| Setting | Default | Meaning |
|---|---|---|
| `candidate_window` | 5 | win% points: moves this close to the best count as "top" |
| `chose_window` | 5 | your played move counts as best among your candidates within this |
| `line_break_threshold` | 10 | a move in your line losing this much is a hole |
| `blind_spot_threshold` / `blind_spot_max` | 10 / 3 | unannotated moves losing this much; at most this many per game |
| `rushed_seconds` / `rushed_clock_fraction` | 30 / 0.5 | a mistake played faster than this with more than this share of the base time left |
| `eval_bands` | [0.5, 1.2, 2.5] | pawn boundaries between `=`, `+=`, `±`, `+-` |
| `glyph_good_window` / `glyph_bad_threshold` / `only_move_window` | 2 / 10 / 5 | move-glyph check |

Win% uses the Lichess formula. So a 2-pawn slip when you're already +8 barely counts, while a 1-pawn slip near equality does.

## Running the tests

```bash
uv run pytest            # everything except live Lichess calls (engine tests use stubs;
                         # two short real-Stockfish tests run if it's installed)
uv run pytest -m network # also download the real study (needs LICHESS_TOKEN)
```

The UI smoke tests open a hidden Tk window. If cairo isn't loadable in the test process, they swap in a board stub so the flow is still tested.

## Database backups and migrations

- On launch, the app adds any new columns it needs. If `blunders.db` already exists, it first copies it to `blunders.db.bak-<YYYYMMDD-HHMMSS>`.
- Before a fix, the parser had `?` and `??` swapped, so wizard entries saved back then may be labelled the wrong way round. To check them:

  ```bash
  python -m core.migrate_f1          # dry run: lists every row it would change
  python -m core.migrate_f1 --apply  # backs up blunders.db, then fixes those rows
  ```

  A row only changes if its original glyph can be re-read from the stored game. Every other row is left alone.
- To try the app without touching your real data: `CHESS_PATTERNS_DB=/tmp/scratch.db python main.py`.
- Engine results live in `blunders.db` tables `analysis_runs`, `decision_points` and `findings`. Wizard entries in `blunders` are never deleted or changed by a re-run.

## Notes

- `blunders.db` and `.env` are not committed to git
- `config.yaml` theme lists can be edited directly or via the in-app Settings screen
- `engine_cache.db` (Stockfish results) is not committed and can be deleted at any time
- `prd.md` describes the whole app: features, data model, decisions and what's still to come
- New themes added via the "Other…" option are saved back to `config.yaml` automatically
