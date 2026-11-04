"""Run one explicitly authorized, secret-safe JSearch transport/API probe."""

from __future__ import annotations

import argparse

from betteroption.jsearch_diagnostics import check_jsearch_access
from betteroption.settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Make one synthetic JSearch request and print only a specific safe category, "
            "count, and fixed troubleshooting guidance."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly authorize one request against the configured JSearch account.",
    )
    arguments = parser.parse_args(argv)
    if not arguments.live:
        print("category: not_run")
        print("result_count: 0")
        print("detail: The live provider probe was not authorized.")
        print("next_step: Rerun with --live to authorize exactly one synthetic request.")
        return 2

    diagnostic = check_jsearch_access(Settings())
    print(f"category: {diagnostic.category}")
    print(f"result_count: {diagnostic.result_count}")
    print(f"detail: {diagnostic.detail}")
    print(f"next_step: {diagnostic.next_step}")
    return 0 if diagnostic.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
