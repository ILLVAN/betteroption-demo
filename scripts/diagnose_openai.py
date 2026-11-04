"""Check OpenAI authentication/model access without printing secrets or sending user text."""

from __future__ import annotations

from betteroption.openai_diagnostics import check_openai_model_access
from betteroption.settings import Settings


def main() -> int:
    diagnostic = check_openai_model_access(Settings())
    print("BetterOption OpenAI diagnostic")
    print(f"- Model: {diagnostic.model}")
    print(f"- Result: {diagnostic.message}")
    return 0 if diagnostic.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
