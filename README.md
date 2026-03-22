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

### 2. Set DYLD_LIBRARY_PATH (macOS only)

On macOS, Python can't find the Cairo library unless you tell it where to look. You need to set the `DYLD_LIBRARY_PATH` environment variable to point to Homebrew's library folder.

**Option A — permanent (recommended):** Add it to your shell profile so it's set automatically in every terminal session.

If you use zsh (default on modern Macs):
```bash
echo 'export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH' >> ~/.zshrc
source ~/.zshrc
```

If you use bash:
```bash
echo 'export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH' >> ~/.bash_profile
source ~/.bash_profile
```

**Option B — per session:** Prefix it on the command line each time you run the app:
```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib python main.py
```

---

### 3. Install Python dependencies

```bash
uv venv
source .venv/bin/activate
uv sync
```

---

### 4. Configure environment variables

Copy the example below into a file named `.env` in the project root and fill in your values:

```env
OLLAMA_API_KEY=your_key_here
OLLAMA_MODEL=llama3
OLLAMA_BASE_URL=https://your-ollama-endpoint.com/v1
```

The app uses these to connect to an Ollama-compatible LLM endpoint for pre-filling classifications and generating training recommendations. If these are missing, the app still works — LLM features are silently skipped.

---

### 5. Run the app

```bash
source .venv/bin/activate
python main.py
```

---

## Getting started

This section walks a new user through a full session from first launch to reviewing patterns.

### Step 1 — Export a game from Lichess

Open the game you want to review on Lichess. Before exporting:

- Make sure the game has annotations. Either Lichess added "?" / "??" symbols automatically (via computer analysis), or you added comments yourself.
- Click **Share & export → Export PGN**, and tick **Include annotations**.
- Copy the full PGN text to your clipboard.

> The app flags moves based on the "?" (mistake) and "??" (blunder) symbols in the PGN, plus any move comments. Games without these will produce no flagged moves.

---

### Step 2 — Import the PGN

1. Launch the app: `python main.py`
2. Paste your PGN into the large text area on the home screen.
3. Click **White** or **Black** to indicate which side you played.
4. Click **Analyse →**.

The app parses the PGN, extracts your flagged moves, and launches the review wizard.

---

### Step 3 — Work through the review wizard

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

After saving, the app automatically fetches relevant Lichess puzzles and (if configured) an LLM recommendation for targeted training.

---

### Step 4 — Review your patterns

Once you have logged several games, click **📊 Patterns** on the home screen to open the patterns dashboard.

The dashboard shows:

- **Thinking step breakdown** — which step fails most often
- **Theme frequency** — your most common mistake themes
- **Move heatmap** — which squares and move numbers you blunder on most
- **Training prescriptions** — what your logged entries suggest you should study
- **Monthly trend** — how your blunder rate is changing over time

---

### Step 5 — Adjust settings

Click **⚙ Settings** on the home screen to:

- Edit the lists of primary and secondary themes shown in the wizard dropdowns
- Update your LLM endpoint, model, and API key
- Change the app appearance theme

Changes are saved to `config.yaml` immediately.

---

## Usage summary

1. Export a game from Lichess with annotations (use the "?" and "??" symbols, or add comments)
2. Paste the PGN into the text area on the home screen
3. Select which colour you played
4. Click **Analyse** — the app finds your blunders, mistakes, and missed wins
5. Work through the wizard for each flagged move:
   - Pick the thinking step that broke down (1–4)
   - Say whether you saw the idea or not
   - Choose a theme and training prescription
   - Optionally add notes
6. After saving, the app fetches targeted Lichess puzzles and an LLM recommendation

---

## File structure

```
chess-patterns/
├── main.py               # app entry point
├── ui/
│   ├── home.py           # home / PGN import screen
│   ├── analyze.py        # wizard screen
│   ├── patterns.py       # patterns dashboard (phase 2 placeholder)
│   └── settings.py       # editable config screen
├── core/
│   ├── pgn_parser.py     # PGN parsing and blunder flagging
│   ├── db.py             # SQLite read/write
│   ├── config.py         # config.yaml loading and saving
│   ├── board_render.py   # FEN → board image pipeline
│   ├── llm.py            # LLM pre-fill and recommendations
│   └── puzzles.py        # Lichess puzzle API
├── config.yaml           # theme lists and settings (edit here or in-app)
├── blunders.db           # SQLite database (auto-created on first run)
├── .env                  # secrets — never commit this file
└── requirements.txt
```

---

## Notes

- `blunders.db` and `.env` are not committed to git
- `config.yaml` theme lists can be edited directly or via the in-app Settings screen
- New themes added via the "Other…" option are saved back to `config.yaml` automatically
