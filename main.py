"""
Compatibility entrypoint.

The original implementation lives in `_legacy_main.py`. This wrapper keeps the
same import surface (`import main`) while enabling the gradual move into the
`jarvis/` package.

Important: We intentionally re-export legacy symbols because existing modules
and integrations may import internal helpers from `main`.
"""

from __future__ import annotations

# Re-export everything legacy exposed (including internal helpers)
from _legacy_main import *  # noqa: F403


def main() -> None:  # noqa: F811
    """
    Primary entrypoint for `python main.py`.
    Delegates to `jarvis.engine` (which currently delegates to `_legacy_main`).
    """

    from jarvis.engine import main as engine_main

    engine_main()


if __name__ == "__main__":
    main()

