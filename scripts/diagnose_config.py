"""Print BetterOption's effective configuration without exposing secret values."""

from __future__ import annotations

import argparse
from pathlib import Path

from betteroption.brave_search import BraveSearchError
from betteroption.config_diagnostics import secret_is_configured, secret_safe_configuration_report
from betteroption.discovery import BraveWebDiscoveryProvider
from betteroption.settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print secret-safe configuration and optionally probe Brave Web Search."
    )
    parser.add_argument(
        "--probe-brave-search",
        action="store_true",
        help=(
            "Make one fixed, non-user-data Web Search request. This consumes one Brave "
            "Search request and verifies Search-plan access."
        ),
    )
    arguments = parser.parse_args(argv)
    settings = Settings()
    print(
        secret_safe_configuration_report(
            settings,
            env_path=Path(".env"),
        )
    )
    if not arguments.probe_brave_search:
        return 0

    key = settings.brave_search_api_key or ""
    if not secret_is_configured({"BRAVE_SEARCH_API_KEY": key}, "BRAVE_SEARCH_API_KEY"):
        print(
            "Brave Search probe: NOT RUN — configure BRAVE_SEARCH_API_KEY with a key "
            "created under an active Brave Search plan."
        )
        return 1
    print("Brave Search probe: making one fixed Web Search request (one Search-plan call).")
    try:
        BraveWebDiscoveryProvider(key).validate_search_access()
    except BraveSearchError as exc:
        print(f"Brave Search probe: FAILED — {exc}")
        return 1
    print(
        "Brave Search probe: PASS — the Web Search endpoint accepted the Search-plan key. "
        "This verifies access, not that every job query will return usable vacancies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
