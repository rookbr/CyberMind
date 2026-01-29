"""Environment and dependency preflight checks.

These checks are intentionally strict because CyberMind targets Fedora + GNOME.
Set CYBERMIND_SKIP_PREFLIGHT=1 to bypass (useful for development).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    message: str


def _read_os_release() -> dict:
    path = Path("/etc/os-release")
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"')
        data[key] = value
    return data


def _is_fedora() -> bool:
    osr = _read_os_release()
    return osr.get("ID", "").lower() == "fedora"


def _is_gnome() -> bool:
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").upper()
    session = (os.environ.get("DESKTOP_SESSION") or "").upper()
    return ("GNOME" in desktop) or ("GNOME" in session)


def _check_python_deps() -> Optional[str]:
    """Return an error message if required deps are missing."""
    try:
        import cairo  # type: ignore[import-not-found]  # noqa: F401
    except Exception as exc:  # pylint: disable=broad-except
        return (
            "Missing Python dependency 'pycairo'. "
            "Install it with pip (pycairo) and ensure cairo is available. "
            f"Underlying error: {exc}"
        )

    try:
        import gi  # type: ignore[import-not-found]

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gtk, Adw, Gdk  # type: ignore[import-not-found]  # noqa: F401
    except Exception as exc:  # pylint: disable=broad-except
        return (
            "Missing GTK/libadwaita bindings. Ensure Fedora packages are installed: "
            "gtk4-devel libadwaita-devel python3-gobject cairo-devel. "
            "(You may not need -devel at runtime, but these are a safe baseline.) "
            f"Underlying error: {exc}"
        )

    return None


def run_preflight(
    *,
    require_fedora: bool = True,
    require_gnome: bool = True,
    check_deps: bool = True,
) -> PreflightResult:
    """Run checks and return a structured result.

    `require_gnome` is best-effort and depends on session env vars, so it's
    typically enforced at runtime (not during `pip install`).
    """
    if os.environ.get("CYBERMIND_SKIP_PREFLIGHT") == "1":
        return PreflightResult(True, "Preflight skipped via CYBERMIND_SKIP_PREFLIGHT=1")

    if require_fedora and not _is_fedora():
        osr = _read_os_release()
        pretty = osr.get("PRETTY_NAME") or osr.get("NAME") or "Unknown distro"
        return PreflightResult(
            False,
            "CyberMind is supported on Fedora (tested on Fedora 43). "
            f"Detected: {pretty}. Set CYBERMIND_SKIP_PREFLIGHT=1 to bypass.",
        )

    if require_gnome and not _is_gnome():
        desktop = os.environ.get("XDG_CURRENT_DESKTOP") or "(unset)"
        session = os.environ.get("DESKTOP_SESSION") or "(unset)"
        return PreflightResult(
            False,
            "CyberMind is supported on GNOME. "
            f"Detected XDG_CURRENT_DESKTOP={desktop}, DESKTOP_SESSION={session}. "
            "Set CYBERMIND_SKIP_PREFLIGHT=1 to bypass.",
        )

    if check_deps:
        dep_error = _check_python_deps()
        if dep_error:
            return PreflightResult(False, dep_error)

    return PreflightResult(True, "Preflight OK")


def run_preflight_or_die(
    *,
    require_fedora: bool = True,
    require_gnome: bool = True,
    check_deps: bool = True,
) -> None:
    result = run_preflight(
        require_fedora=require_fedora,
        require_gnome=require_gnome,
        check_deps=check_deps,
    )
    if result.ok:
        return

    sys.stderr.write("\nCyberMind preflight check failed:\n")
    sys.stderr.write(result.message)
    sys.stderr.write("\n\n")
    sys.stderr.write(
        "Suggested Fedora setup:\n"
        "  sudo dnf install gtk4-devel libadwaita-devel python3-gobject cairo-devel\n"
        "  pip install -r requirements.txt\n\n"
    )
    raise SystemExit(1)
