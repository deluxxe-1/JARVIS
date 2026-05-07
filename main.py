"""
Main entrypoint for JARVIS.

This wrapper keeps the `python main.py` execution while fully
delegating all logic to the modular `jarvis/` package.
"""
from __future__ import annotations

from jarvis.engine import main as engine_main

def main() -> None:
    """
    Primary entrypoint for `python main.py`.
    Delegates to `jarvis.engine`.
    """
    engine_main()

if __name__ == "__main__":
    main()
