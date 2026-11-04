"""Small runtime checks for local alpha commands."""

from __future__ import annotations

import os
import sys


def is_virtual_environment() -> bool:
    """Return whether the current Python process appears to run inside a venv."""

    return bool(os.environ.get("VIRTUAL_ENV")) or sys.prefix != getattr(
        sys,
        "base_prefix",
        sys.prefix,
    )


def print_virtual_environment_warning() -> None:
    if is_virtual_environment():
        return
    print("WARNING: This command is running outside the project virtual environment.")
    print("Activate it first with: .venv\\Scripts\\Activate.ps1\n")
