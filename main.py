"""chess-patterns — app entry point."""

import os
import sys

# Make cairosvg findable on macOS with Homebrew cairo
homebrew_lib = "/opt/homebrew/lib"
if sys.platform == "darwin" and os.path.isdir(homebrew_lib):
    existing = os.environ.get("DYLD_LIBRARY_PATH", "")
    if homebrew_lib not in existing:
        os.environ["DYLD_LIBRARY_PATH"] = f"{homebrew_lib}:{existing}" if existing else homebrew_lib

from dotenv import load_dotenv
load_dotenv()

import customtkinter as ctk
from core.db import init_db
from core.config import load_config, ensure_config
from ui.home import HomeScreen

APP_TITLE = "chess-patterns"
APP_GEOMETRY = "1100x780"


def main():
    ensure_config()
    init_db()

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = ctk.CTk()
    app.title(APP_TITLE)
    app.geometry(APP_GEOMETRY)
    app.minsize(900, 650)

    HomeScreen(app).pack(fill="both", expand=True)

    app.mainloop()


if __name__ == "__main__":
    main()
