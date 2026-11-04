"""Keep automated tests independent from the operator's runtime `.env`."""

from __future__ import annotations

import os

import pytest

from betteroption.settings import Settings


@pytest.fixture(autouse=True)
def isolate_runtime_dotenv(monkeypatch: pytest.MonkeyPatch):
    """Do not let real local provider keys or modes alter test expectations.

    Environment changes made inside an individual test and an explicit
    `_env_file=` still work. Ambient provider/runtime variables and the implicit
    project-root `.env` lookup are removed before each test starts.
    """

    for key in tuple(os.environ):
        if key.startswith("BETTEROPTION_") or key in {
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "BRAVE_SEARCH_API_KEY",
            "BRAVE_ANSWERS_API_KEY",
            "EXA_API_KEY",
            "YOU_SEARCH_API_KEY",
            "YDC_API_KEY",
            "BETTEROPTION_YOU_SEARCH_API_KEY",
            "GOOGLE_ROUTES_API_KEY",
            "OPENROUTESERVICE_API_KEY",
            "APIFY_API_TOKEN",
        }:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
