# chess-patterns — specification

A desktop app for logging, classifying, and analysing chess blunders and mistakes, with the goal of identifying long-term patterns and generating targeted training recommendations.

---

## Tech stack

| Concern | Choice |
|---|---|
| UI framework | CustomTkinter |
| Chess logic + PGN parsing | python-chess |
| Board rendering | python-chess SVG → cairosvg → Pillow → CTkImage |
| Database | SQLite (via Python built-in `sqlite3`) |
| Config / theme lists | `config.yaml` (via pyyaml) |
| LLM (pre-fill + puzzle explanation) | Ollama-compatible API (OpenAI-style endpoint) |
| Puzzle fetching | Lichess public puzzle API |
| Env / secrets | `.env` file (via python-dotenv) |

### Python packages to install (venv)
```
customtkinter
python-chess
cairosvg
Pillow
pyyaml
python-dotenv
requests
openai  # used as the client for Ollama-compatible endpoint
```

---

## File structure

```
chess-patterns/
├── main.py                  # app entry point
├── ui/
│   ├── analyze.py           # main wizard screen
│   ├── patterns.py          # patterns dashboard (phase 2)
│   └── settings.py          # editable config screen
├── core/
│   ├── pgn_parser.py        # PGN parsing + flagging logic
│   ├── db.py                # SQLite read/write
│   ├── llm.py               # LLM pre-fill + puzzle explanation
│   └── puzzles.py           # Lichess puzzle API calls
├── blunders.db              # SQLite database (auto-created on first run)
├── config.yaml              # user-editable theme lists and settings
├── .env                     # secrets — never commit
├── requirements.txt
└── README.md
```

---

## Environment variables (`.env`)

```env
OLLAMA_API_KEY=your_key_here
OLLAMA_MODEL=llama3
OLLAMA_BASE_URL=https://your-ollama-endpoint.com/v1
```

The app loads these at startup via `python-dotenv`. If any are missing it shows a clear error message pointing to `.env`.

---

## Config file (`config.yaml`)

This file is the user-editable schema layer. The app reads it at startup and whenever the Settings screen is saved. Users can edit it directly in any text editor, or via the Settings screen inside the app.

```yaml
primary_themes:
  - Fork
  - Pin
  - Skewer
  - Back rank
  - Mating net
  - Discovered attack
  - Zwischenzug
  - Piece activity
  - Pawn structure
  - King safety
  - Prophylaxis
  - Calculation error
  - Endgame technique
  - Opening prep gap

secondary_themes:
  - None
  - Time pressure
  - Opening prep gap
  - Endgame technique
  - King safety
  - Opponent surprise

training_prescriptions:
  - Tactics puzzles (general)
  - Fork puzzles
  - Pin and skewer puzzles
  - Back rank puzzles
  - Mating net puzzles
  - Threat scan practice
  - Positional study
  - Calculation training
  - Play slower time controls
  - Endgame study
  - Opening review

# Mapping from our theme names to Lichess puzzle API angle slugs.
# Used to fetch targeted puzzles. Add entries here as new themes are added.
lichess_theme_map:
  Fork: fork
  Pin: pin
  Skewer: skewer
  Back rank: backRankMate
  Mating net: matingNet
  Discovered attack: discoveredAttack
  Zwischenzug: zwischenzug
  Piece activity: quietMove
  King safety: kingsideAttack
  Endgame technique: endgame
  Calculation error: hangingPiece

# Eval swing threshold in centipawns for flagging missed wins
missed_win_threshold: 150

# Minimum eval (in centipawns, from your side) to consider a position "winning"
# before the swing, for missed win detection
winning_threshold: 150
```

### "Other" theme flow
If the user selects "Other…" from either theme dropdown, a text input appears inline. On saving the entry, the new theme is:
1. Stored in the database entry as-is
2. Appended to the appropriate list in `config.yaml`
3. Available as a first-class option in dropdowns from next launch

---

## Database schema (`blunders.db`)

### Table: `games`
```sql
CREATE TABLE games (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  logged_at   TEXT NOT NULL,           -- ISO datetime
  white       TEXT,
  black       TEXT,
  result      TEXT,                    -- "1-0", "0-1", "1/2-1/2"
  time_control TEXT,
  played_at   TEXT,                    -- date of the game
  pgn_raw     TEXT NOT NULL            -- full PGN text as pasted
);
```

### Table: `blunders`
```sql
CREATE TABLE blunders (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id             INTEGER REFERENCES games(id),
  logged_at           TEXT NOT NULL,
  move_number         INTEGER NOT NULL,
  move_side           TEXT NOT NULL,   -- "white" or "black"
  move_san            TEXT NOT NULL,   -- e.g. "Nxe5"
  fen                 TEXT NOT NULL,   -- position before the move
  lichess_url         TEXT,            -- deep link to that move in Lichess
  flag_type           TEXT NOT NULL,   -- "blunder", "mistake", "missed_win"
  annotation          TEXT,            -- raw comment from PGN if present
  step                INTEGER,         -- 1 / 2 / 3 / 4
  layer               TEXT,            -- "didnt_see" or "got_it_wrong"
  diagnosis           TEXT,            -- auto-generated from step + layer
  primary_theme       TEXT,
  secondary_theme     TEXT,
  one_sentence_fix    TEXT,
  training_prescription TEXT,
  puzzle_urls         TEXT,            -- JSON array of Lichess puzzle URLs
  llm_recommendation  TEXT,            -- LLM's qualitative explanation
  notes               TEXT
);
```

Schema changes over time: add new columns with `ALTER TABLE blunders ADD COLUMN ...` — existing rows will have NULL for new fields, which is fine.

---

## PGN parsing logic (`core/pgn_parser.py`)

Input: raw PGN text pasted by the user.

Flagging logic — a move is surfaced if ANY of these are true:
1. It has a NAG code for blunder (`$2`) or mistake (`$4`)
2. It has a text comment in curly braces `{ ... }`
3. It has an eval annotation and the centipawn swing from that move exceeds `missed_win_threshold` from a position where the player was winning (above `winning_threshold`) — this is the missed win detection

For each flagged move, extract:
- Move number and side (white/black)
- SAN notation
- FEN of the position *before* the move (using `python-chess` board state)
- The text comment if present
- The flag type (blunder / mistake / missed_win)
- A Lichess deep link: `https://lichess.org/analysis/{fen_url_encoded}` pointing to that position

Only flag moves where the *user's* side was playing. The app needs to know which colour the user played — infer this from the PGN headers (ask the user to confirm if ambiguous).

---

## App screens

### 1. Home / game import screen

Shown on launch if no game is being analysed.

Elements:
- Large text area: "Paste PGN here"
- "Which colour did you play?" — two buttons: White / Black
- "Analyse" button — parses PGN, extracts flagged moves, transitions to wizard
- Summary line below button: "Found N blunders, M mistakes, K missed wins"

If the PGN has no flagged moves at all, show a message: "No annotated moves found. Add ? or ?? symbols or comments in Lichess before exporting."

---

### 2. Analyse screen (wizard)

This is the core screen. For each flagged move in sequence:

**Left panel — board + context**
- Move label: "Move 23 · Black · Blunder"
- Chess board rendered from FEN (256×256 px minimum), with the moved square highlighted (from-square in green tint, to-square in red tint)
- "Open in Lichess ↗" link
- Annotation box (shown only if a comment exists in the PGN): displays the raw comment text with a subtle left border accent
- Progress indicator: "2 of 3 flagged moves"

**Right panel — wizard fields** (in this order):

| # | Field | Widget | Notes |
|---|---|---|---|
| 1 | Thinking step | Dropdown | Step 1 – missed opponent threat / Step 2 – missed own tactic / Step 3 – wrong plan / Step 4 – no blunder check |
| 2 | Did you see it? | Two buttons | "Didn't see it" / "Saw it, got it wrong" |
| 3 | Diagnosis | Auto-generated text line | Shown once step + layer are both selected. See diagnosis table below. |
| 4 | Primary theme | Dropdown | From config.yaml. Includes "Other…" option. |
| 5 | Secondary theme | Dropdown | From config.yaml. Includes "None" and "Other…". |
| 6 | One-sentence fix | Short text input | "What would you do differently next time?" |
| 7 | Training prescription | Dropdown | From config.yaml. |
| 8 | Notes | Multiline text area (optional) | Pre-populated with the PGN annotation comment if present. |

Buttons at bottom: **Skip** (don't log this move, go to next) | **Save → next**

On Save:
1. Write row to `blunders` table
2. Trigger async puzzle fetch (Lichess API) + LLM recommendation call
3. Show puzzle links + LLM text in a panel below the wizard fields (non-blocking — appears when ready)
4. After user has reviewed, they click "Next move →" to proceed

**LLM pre-fill behaviour:**
- If a PGN comment exists on this move, send it to the LLM on entry to the wizard step
- LLM returns suggested `step` (1-4) and `layer` ("didnt_see" / "got_it_wrong")
- These are silently pre-selected in the dropdowns — no badge or label indicating AI origin
- User can change them freely

---

### Diagnosis auto-generation

Generated client-side (no LLM call needed) from the step × layer combination:

| Step | Layer | Diagnosis |
|---|---|---|
| 1 | Didn't see it | Scanning gap — you're not pausing to read your opponent's move |
| 1 | Got it wrong | Defensive misjudgement — you saw the threat but chose the wrong response |
| 2 | Didn't see it | Pattern recognition gap — you're not scanning for your own tactics |
| 2 | Got it wrong | Calculation error — you found the idea but miscalculated the line |
| 3 | Didn't see it | Positional knowledge gap — the right plan wasn't visible to you |
| 3 | Got it wrong | Evaluation error — you saw the plans but chose the inferior one |
| 4 | Didn't see it | Habit gap — you skipped the blunder check entirely |
| 4 | Got it wrong | Calculation under pressure — blunder check ran but missed their best reply |

---

### Puzzle recommendation panel

Appears below the wizard after Save, while classification moves to next step.

Two parts:
1. **Lichess puzzles** — 3-5 clickable puzzle links fetched from `lichess.org/api/puzzle/next?angle={angle}` using the `lichess_theme_map` from config.yaml. If no mapping exists for the chosen theme, skip the Lichess fetch gracefully.
2. **LLM recommendation** — a short paragraph (3-5 sentences) from the LLM explaining *why* these puzzles address the specific blind spot, based on the full classification. Prompt includes: step, layer, diagnosis, primary theme, secondary theme, annotation, one-sentence fix.

Both are fetched asynchronously. Show a subtle loading indicator ("fetching puzzles…") that disappears when results arrive.

---

### 3. Settings screen

A single scrollable panel with editable text areas — one per list from `config.yaml`:

- Primary themes (one per line)
- Secondary themes (one per line)  
- Training prescriptions (one per line)
- Lichess theme map (shown as a simple two-column editable table: Our theme | Lichess angle)

**Save** button writes changes back to `config.yaml`. Dropdowns in the wizard reflect changes immediately on next game load.

---

### 4. Patterns screen (phase 2 — build later)

Placeholder for now. Will display:
- Breakdown of blunders by Step (bar chart)
- Breakdown by theme (bar chart)
- Step × Layer heatmap
- Trend over time (line chart — Step breakdown by month)
- Most frequent training prescription triggered

This screen reads entirely from the `blunders` table and requires no additional data collection.

---

## LLM integration details (`core/llm.py`)

Uses the `openai` Python client pointed at the Ollama-compatible endpoint from `.env`.

```python
from openai import OpenAI
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
```

Two calls:

**1. Pre-fill call** (triggered on entering a wizard step with a comment)

System prompt:
```
You are a chess coach assistant. Given a player's annotation of their own chess mistake, classify it using two dimensions:

1. Which thinking step broke down?
   - Step 1: player missed opponent's threat or intention
   - Step 2: player missed their own tactic or forcing move
   - Step 3: player chose the wrong strategic plan or piece improvement
   - Step 4: player failed to check opponent's response before playing

2. Did they see the possibility?
   - didnt_see: the idea never occurred to them
   - got_it_wrong: they saw something but miscalculated or misjudged

Respond only with valid JSON like: {"step": 2, "layer": "didnt_see"}
No explanation, no markdown, just the JSON object.
```

User message: the annotation text.

**2. Recommendation call** (triggered after Save)

System prompt:
```
You are a chess coach. Given a classified chess mistake, write a short 3-5 sentence recommendation explaining what specific pattern the player needs to train, why the suggested puzzles address their blind spot, and one concrete piece of advice for their next game. Be direct and specific. Do not repeat the classification back to them.
```

User message: JSON summary of the full classification (step, layer, diagnosis, primary_theme, secondary_theme, annotation, one_sentence_fix).

---

## Lichess puzzle API (`core/puzzles.py`)

Endpoint: `GET https://lichess.org/api/puzzle/next?angle={angle}`

Returns one puzzle per call. Call it 3-5 times with a small delay to get a set. Parse the response for:
- `puzzle.id` → construct URL: `https://lichess.org/training/{id}`
- `puzzle.themes` → display as tags

No authentication required for this endpoint.

Handle gracefully: if the theme has no Lichess mapping, or the API call fails, show "No targeted puzzles found for this theme — try searching Lichess puzzle themes manually."

---

## Error handling and edge cases

- PGN with no annotations → friendly message, don't crash
- LLM call fails or times out → wizard still works, pre-fill just doesn't happen; recommendation panel shows "Recommendation unavailable"
- Lichess puzzle API unreachable → show message, don't block saving
- `config.yaml` missing → create it with defaults on first run
- `blunders.db` missing → create it with schema on first run
- "Other…" theme with empty text input → don't save, show inline validation message

---

## Not in scope (phase 1)

- Patterns dashboard (Settings and Analyse screens only in phase 1)
- Automatic Chess.com → Lichess sync
- User accounts or multi-user support
- Any cloud sync of the database

---

## Open questions / future ideas

- Add a "Review mode" that surfaces old blunders as flashcards for spaced repetition
- Export blunders as a Lichess study (via Lichess API write endpoints — requires OAuth)
- Link from Patterns screen to the original game position for any data point
