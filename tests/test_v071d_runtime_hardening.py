from __future__ import annotations

from pathlib import Path

from betteroption.settings import Settings


def test_test_harness_does_not_read_the_operator_dotenv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "BRAVE_SEARCH_API_KEY=a-real-looking-local-key\nBETTEROPTION_APP_ENVIRONMENT=staging\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.brave_search_api_key is None
    assert settings.app_environment == "local"
