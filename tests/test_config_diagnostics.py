from __future__ import annotations

from pathlib import Path

from betteroption.brave_search import BraveSearchPlanError
from betteroption.config_diagnostics import (
    duplicate_environment_keys,
    secret_safe_configuration_report,
)
from betteroption.settings import Settings
from scripts import diagnose_config


def test_duplicate_environment_keys_reports_lines_without_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "BETTEROPTION_REGISTRATION_MODE=first_user",
                "OPENAI_API_KEY=top-secret",
                "# BETTEROPTION_REGISTRATION_MODE=open",
                "BETTEROPTION_REGISTRATION_MODE=disabled",
            ]
        ),
        encoding="utf-8",
    )

    duplicates = duplicate_environment_keys(env_path)

    assert duplicates == {"BETTEROPTION_REGISTRATION_MODE": [1, 4]}


def test_configuration_report_is_effective_and_secret_safe(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "BETTEROPTION_REGISTRATION_MODE=first_user",
                "BETTEROPTION_REGISTRATION_MODE=disabled",
                "EXA_API_KEY=file-only-secret",
                "GOOGLE_ROUTES_API_KEY=",
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        auth_mode="accounts",
        registration_mode="disabled",
        provider_daily_operation_limit=1_000,
        provider_action_operation_limit=200,
        salary_research_enabled=True,
        salary_research_max_jobs=7,
        salary_research_max_tool_calls=6,
        match_evidence_max_jobs=9,
    )

    report = secret_safe_configuration_report(
        settings,
        environment={
            "OPENAI_API_KEY": "top-secret",
            "BRAVE_SEARCH_API_KEY": "another-secret",
            "BETTEROPTION_YOU_SEARCH_API_KEY": "you-alias-secret",
            "OPENWEBNINJA_JSEARCH_API_KEY": "jsearch-secret",
            "APIFY_API_TOKEN": "apify-secret",
        },
        env_path=env_path,
    )

    assert "Authentication: accounts" in report
    assert "Registration: disabled" in report
    assert "daily operations=1000" in report
    assert "workflow operations=200" in report
    assert "OpenAI configured" in report
    assert "Brave Search (BRAVE_SEARCH_API_KEY): configured" in report
    assert "Brave Answers (BRAVE_ANSWERS_API_KEY): not configured and unused" in report
    assert "You.com Search (YDC_API_KEY; aliases" in report
    assert "configured via supported alias" in report
    assert "OpenWebNinja JSearch (OPENWEBNINJA_JSEARCH_API_KEY): configured" in report
    assert "EURES via Apify (APIFY_API_TOKEN): configured" in report
    assert "JobsPipe via Apify (APIFY_API_TOKEN): configured" in report
    assert "All Jobs Scraper via Apify (APIFY_API_TOKEN): configured" in report
    assert "results per platform=20" in report
    assert "readback/presentation max items=120" in report
    assert "pay-per-event charge ceiling USD=0.40" in report
    assert "estimated cost/run USD=0.40" in report
    assert "call all configured providers=true" in report
    assert "Exa configured" in report
    assert "Google Routes not configured" in report
    assert "Salary research: enabled=true" in report
    assert "max jobs=7" in report
    assert "max Web Search calls=6" in report
    assert "public job evidence only" in report
    assert "Semantic match evidence: provider=openai; OpenAI key=configured" in report
    assert "max jobs=9; fixed batches of 5" in report
    assert "BETTEROPTION_REGISTRATION_MODE: lines 1, 2" in report
    assert "top-secret" not in report
    assert "another-secret" not in report
    assert "you-alias-secret" not in report
    assert "jsearch-secret" not in report
    assert "apify-secret" not in report
    assert "file-only-secret" not in report


def test_configuration_report_recognizes_every_you_search_key_without_exposing_it(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    for key in (
        "YDC_API_KEY",
        "BETTEROPTION_YOU_SEARCH_API_KEY",
        "YOU_SEARCH_API_KEY",
    ):
        secret = f"secret-for-{key.casefold()}"
        report = secret_safe_configuration_report(
            Settings(_env_file=None, database_url="sqlite:///:memory:"),
            environment={key: secret},
            env_path=env_path,
        )

        assert "You.com Search (YDC_API_KEY; aliases" in report
        assert (
            "configured via YDC_API_KEY"
            if key == "YDC_API_KEY"
            else "configured via supported alias"
        ) in report
        assert secret not in report


def test_configuration_report_rejects_you_search_placeholders(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("YDC_API_KEY=<YOUR_API_KEY>\n", encoding="utf-8")

    report = secret_safe_configuration_report(
        Settings(_env_file=None, database_url="sqlite:///:memory:"),
        environment={},
        env_path=env_path,
    )

    assert "YOU_SEARCH_API_KEY): not configured" in report


def test_configuration_report_does_not_treat_placeholders_as_keys(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEY=replace-with-your-project-key\nBRAVE_SEARCH_API_KEY=<YOUR_API_KEY>\n",
        encoding="utf-8",
    )

    report = secret_safe_configuration_report(
        Settings(_env_file=None, database_url="sqlite:///:memory:"),
        environment={},
        env_path=env_path,
    )

    assert "OpenAI not configured" in report
    assert "Brave Search (BRAVE_SEARCH_API_KEY): not configured" in report


def test_configuration_report_warns_when_salary_research_has_no_openai_key(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("BETTEROPTION_SALARY_RESEARCH_ENABLED=true\n", encoding="utf-8")

    report = secret_safe_configuration_report(
        Settings(
            _env_file=None,
            database_url="sqlite:///:memory:",
            salary_research_enabled=True,
        ),
        environment={},
        env_path=env_path,
    )

    assert "Salary research warning" in report
    assert "configure OPENAI_API_KEY" in report


def test_configuration_report_warns_for_a_superseded_privacy_draft(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-01-draft\n",
        encoding="utf-8",
    )

    report = secret_safe_configuration_report(
        Settings(
            _env_file=None,
            database_url="sqlite:///:memory:",
            legal_privacy_version="2026-08-01-draft",
        ),
        environment={},
        env_path=env_path,
    )

    assert "Privacy notice warning" in report
    assert "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-05-feedback-draft" in report


def test_configuration_report_warns_that_brave_answers_is_not_a_search_key(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("BRAVE_ANSWERS_API_KEY=answers-secret", encoding="utf-8")

    report = secret_safe_configuration_report(
        Settings(_env_file=None, database_url="sqlite:///:memory:"),
        environment={},
        env_path=env_path,
    )

    assert "Brave Search (BRAVE_SEARCH_API_KEY): not configured" in report
    assert "Brave Answers (BRAVE_ANSWERS_API_KEY): configured but unused" in report
    assert "an Answers-only key cannot authorize Explore" in report
    assert "answers-secret" not in report


def test_configuration_report_explains_local_open_registration_and_legacy_alias(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BETTEROPTION_EXA_FALLBACK_MIN_RESULTS=15\n",
        encoding="utf-8",
    )

    report = secret_safe_configuration_report(
        Settings(
            _env_file=None,
            database_url="sqlite:///:memory:",
            auth_mode="accounts",
            registration_mode="open",
            app_environment="local",
        ),
        environment={},
        env_path=env_path,
    )

    assert "open permits new test accounts" in report
    assert "supported legacy alias" in report
    assert "inactive while call-all-providers is true" in report
    assert "zero USD ceiling disables" in report


def test_configuration_report_warns_about_unsafe_hosted_basics(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    report = secret_safe_configuration_report(
        Settings(
            _env_file=None,
            app_environment="staging",
            public_base_url="",
            database_url="sqlite:///:memory:",
            auth_mode="accounts",
            registration_mode="open",
            auth_secure_cookie=False,
            auth_rate_limit_secret="",
            operator_emails="",
        ),
        environment={},
        env_path=env_path,
    )

    assert "PUBLIC_BASE_URL must be the public HTTPS URL" in report
    assert "AUTH_SECURE_COOKIE must be true" in report
    assert "invite_only or disabled registration" in report
    assert "use PostgreSQL instead of SQLite" in report
    assert "deployment-specific AUTH_RATE_LIMIT_SECRET" in report
    assert "configure BETTEROPTION_OPERATOR_EMAILS" in report


def test_live_brave_probe_reports_a_safe_plan_failure(
    monkeypatch,
    capsys,
) -> None:
    secret = "brave-secret-that-must-stay-hidden"
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        brave_search_api_key=secret,
    )

    class Probe:
        def __init__(self, api_key: str) -> None:
            assert api_key == secret

        def validate_search_access(self) -> None:
            raise BraveSearchPlanError("Brave Web Search denied Search-product access (HTTP 403).")

    monkeypatch.setattr(diagnose_config, "Settings", lambda: settings)
    monkeypatch.setattr(diagnose_config, "BraveWebDiscoveryProvider", Probe)

    assert diagnose_config.main(["--probe-brave-search"]) == 1
    output = capsys.readouterr().out
    assert "Brave Search probe: FAILED" in output
    assert "HTTP 403" in output
    assert secret not in output
