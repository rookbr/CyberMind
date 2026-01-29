"""CyberMind launcher.

Provides a stable entry point that runs preflight checks before importing
GTK-related modules, which gives clearer error messages on new systems.
"""

from __future__ import annotations

import sys


def main() -> int:
    from cybermind.preflight import run_preflight_or_die

    run_preflight_or_die(require_fedora=True, require_gnome=True, check_deps=True)

    from cybermind.app import main as app_main

    return int(app_main())


if __name__ == "__main__":
    raise SystemExit(main())
