"""
Main entrypoint for AARIS.

This wrapper keeps the `python main.py` execution while fully
delegating all logic to the modular `aaris/` package.
"""
from __future__ import annotations

from aaris.engine import main as engine_main

def main() -> None:
    """
    Primary entrypoint for `python main.py`.
    Delegates to `aaris.engine`.
    """
    engine_main()

if __name__ == "__main__":
    main()
