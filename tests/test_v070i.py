from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from betteroption.deployment import describe, inspect_preflight, migrate
from betteroption.settings import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deployment_description_never_prints_database_credentials(capsys) -> None:
    describe("postgresql+psycopg://betteroption:never-print-me@db/betteroption")

    output = capsys.readouterr().out
    assert "Database backend: postgresql" in output
    assert "Database host: db" in output
    assert "never-print-me" not in output
    assert "betteroption@" not in output


def test_deployment_migrate_creates_the_packaged_schema(tmp_path: Path, capsys) -> None:
    database_path = tmp_path / "staging-smoke.db"
    database_url = f"sqlite:///{database_path.as_posix()}"

    migrate(database_url)

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert "alembic_version" in tables
    assert "accounts" in tables
    assert "background_tasks" in tables
    assert "database schema is current" in capsys.readouterr().out


def test_staging_topology_keeps_every_origin_service_private_behind_tunnel() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    db_section = compose.split("\n  app:", 1)[0]
    app_section = compose.split("\n  app:", 1)[1].split("\n  caddy:", 1)[0]
    caddy_section = compose.split("\n  caddy:", 1)[1].split("\n  cloudflared:", 1)[0]
    tunnel_section = compose.split("\n  cloudflared:", 1)[1].split("\n  backup:", 1)[0]

    assert "\n    ports:" not in db_section
    assert '      - "8000"' in app_section
    assert "\n    ports:" not in caddy_section
    assert '      - "80"' in caddy_section
    assert "cloudflare/cloudflared:2026.7.3" in tunnel_section
    assert "TUNNEL_TOKEN_FILE: /run/secrets/cloudflared_token" in tunnel_section
    assert "TUNNEL_METRICS: 0.0.0.0:2000" in tunnel_section
    assert '["CMD", "cloudflared", "tunnel", "ready"]' in tunnel_section
    assert "file: ./deploy/cloudflared-token" in compose
    assert "deploy/.env.staging" in compose
    assert "/health/ready" in compose


def test_online_startup_requires_accounts_secure_cookies_and_migrations() -> None:
    script = (PROJECT_ROOT / "deploy" / "scripts" / "start_app.sh").read_text(encoding="utf-8")

    assert 'BETTEROPTION_AUTH_MODE:-}" != "accounts"' in script
    assert 'BETTEROPTION_AUTH_SECURE_COOKIE:-}" != "true"' in script
    assert "BETTEROPTION_RUN_STARTUP_MIGRATIONS:-true" in script
    assert "BETTEROPTION_RUN_STARTUP_MIGRATIONS must be true or false" in script
    assert script.index("python -m betteroption.deployment migrate") < script.index(
        "python -m uvicorn"
    )
    assert "--workers 1" in script
    assert "--no-access-log" in script


def test_backup_and_restore_are_bounded_and_verifiable() -> None:
    backup = (PROJECT_ROOT / "deploy" / "scripts" / "backup_postgres.sh").read_text(
        encoding="utf-8"
    )
    restore = (PROJECT_ROOT / "deploy" / "scripts" / "restore_postgres.sh").read_text(
        encoding="utf-8"
    )

    assert "pg_dump" in backup
    assert "sha256sum" in backup
    assert "BACKUP_RETENTION_DAYS" in backup
    assert 'ALLOW_RESTORE:-}" != "true"' in restore
    assert "/backups/*.dump" in restore
    assert "sha256sum -c" in restore
    assert "pg_restore" in restore


def test_legal_iteration_schedules_retention_and_omits_request_uri_logs() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    caddy = (PROJECT_ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    backup_loop = (PROJECT_ROOT / "deploy" / "scripts" / "backup_loop.sh").read_text(
        encoding="utf-8"
    )

    assert "\n  retention:" in compose
    assert '"-m", "betteroption.retention", "loop"' in compose
    assert "\n  backup-scheduler:" in compose
    assert "BACKUP_INTERVAL_SECONDS" in compose
    assert "no HTTP access log" in caddy
    assert "access.log" not in caddy
    assert "format json" not in caddy
    assert "backup_postgres.sh" in backup_loop


def staging_settings(**overrides) -> Settings:
    values = {
        "database_url": (
            "postgresql+psycopg://betteroption:0123456789abcdef0123456789abcdef@db/betteroption"
        ),
        "app_environment": "staging",
        "public_base_url": "https://staging.betteroption.example",
        "auth_mode": "accounts",
        "registration_mode": "disabled",
        "auth_secure_cookie": True,
        "auth_rate_limit_secret": "0123456789abcdef" * 4,
        "operator_emails": "owner@example.com",
        "openai_input_cost_per_million_usd": 1,
        "openai_output_cost_per_million_usd": 2,
        "provider_daily_cost_limit_usd": 10,
        "provider_action_cost_limit_usd": 2,
        "legal_review_completed": True,
        "processor_review_completed": True,
        "incident_plan_ready": True,
        "backup_restore_tested": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_staging_preflight_accepts_a_complete_secret_free_boundary() -> None:
    report = inspect_preflight(staging_settings(), openai_api_key_present=True)

    assert report.ready
    assert report.errors == ()
    assert report.warnings == ()
    assert "PostgreSQL is configured." in report.passed


def test_staging_preflight_blocks_local_or_insecure_configuration() -> None:
    report = inspect_preflight(
        staging_settings(
            database_url="sqlite:///local-data/betteroption.db",
            app_environment="local",
            public_base_url="http://localhost:8000",
            auth_mode="local",
            auth_secure_cookie=False,
            operator_emails="",
        ),
        openai_api_key_present=False,
    )

    assert not report.ready
    assert len(report.errors) == 7
    assert any("PostgreSQL" in error for error in report.errors)
    assert any("absolute HTTPS URL" in error for error in report.errors)
    assert any("operator" in error for error in report.errors)
    assert any("OPENAI_API_KEY" in warning for warning in report.warnings)


def test_staging_preflight_rejects_placeholder_password_without_printing_it(capsys) -> None:
    from betteroption.deployment import preflight

    settings = staging_settings(
        database_url="postgresql+psycopg://betteroption:replace-this-secret@db/betteroption"
    )

    assert not preflight(settings)
    output = capsys.readouterr().out
    assert "database password" in output
    assert "replace-this-secret" not in output


def test_deploy_script_runs_preflight_before_starting_services() -> None:
    script = (PROJECT_ROOT / "deploy" / "scripts" / "deploy_staging.sh").read_text(encoding="utf-8")

    assert "app -m betteroption.deployment preflight" in script
    assert "build migrate app worker retention" in script
    database_start = script.index("up --detach --wait db")
    migration = script.index("up --no-deps migrate")
    preflight = script.index("app -m betteroption.deployment preflight")
    full_start = script.index("up --detach --build --wait")
    assert database_start < migration < preflight < full_start
