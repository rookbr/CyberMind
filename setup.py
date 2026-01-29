#!/usr/bin/env python3
"""Setup script for CyberMind."""

import os
import sys
from setuptools import setup, find_packages


def _run_install_preflight() -> None:
    """Fail fast on unsupported environments.

    Note: installing from a wheel will not execute setup.py, so we also
    enforce this at runtime via `cybermind.launcher`.
    """
    if os.environ.get("CYBERMIND_SKIP_PREFLIGHT") == "1":
        return
    try:
        from cybermind.preflight import run_preflight_or_die
        # Install-time constraints: detect Fedora early.
        # Do NOT require a GNOME session env var at install time, and do NOT
        # require Python deps before pip has had a chance to install them.
        run_preflight_or_die(require_fedora=True, require_gnome=False, check_deps=False)
    except SystemExit:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        sys.stderr.write("\nCyberMind preflight error while installing:\n")
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1)


_run_install_preflight()

setup(
    name="cybermind",
    version="1.0.0",
    description="A hacker-aesthetic mindmap application for Linux",
    author="CyberMind Project",
    license="MIT",
    packages=find_packages(),
    package_data={
        "cybermind": ["theme.css"],
    },
    include_package_data=True,
    python_requires=">=3.11",
    install_requires=[
        "PyGObject>=3.46.0",
        "pycairo>=1.25.0",
    ],
    entry_points={
        "console_scripts": [
            "cybermind=cybermind.launcher:main",
            "cybermind-migrate=cybermind.migrate:main",
        ],
        "gui_scripts": [
            "cybermind-gui=cybermind.launcher:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: X11 Applications :: GTK",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Office/Business",
    ],
)
