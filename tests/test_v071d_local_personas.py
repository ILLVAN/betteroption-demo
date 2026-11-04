"""v0.7.1e account-owned persona and tenant-boundary regressions.

The filename is retained so installing an overlay also replaces the former
v0.7.1d tests that treated a persona as a password-protected account.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.settings import Settings
from betteroption.web import create_app


PASSWORD = "correct horse battery staple"


def account_settings(tmp_path: Path, *, registration_mode: str = "open") -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'personas.db').as_posix()}",
        app_environment="local",
        auth_mode="accounts",
        registration_mode=registration_mode,
        account_personas_enabled=True,
        persona_limit=5,
        background_worker_enabled=False,
        employer_homepage_research=False,
    )


def register(client: TestClient, email: str, display_name: str):
    return client.post(
        "/register",
        data={
            "email": email,
            "display_name": display_name,
            "password": PASSWORD,
            "accept_terms": "yes",
            "acknowledge_privacy": "yes",
            "confirm_adult": "yes",
        },
        follow_redirects=False,
    )


def test_email_accounts_own_passwordless_private_persona_slots(tmp_path: Path) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    app = create_app(container, data_directory=tmp_path / "data")

    with (
        TestClient(app) as alice_client,
        TestClient(app) as bob_client,
    ):
        assert register(alice_client, "alice@example.com", "Alice").status_code == 303
        (alice,) = container.accounts.list_accounts()
        (alice_main,) = container.personas.list_for_account(alice.id)
        assert alice_main.name == "Main"

        renamed = alice_client.post(
            f"/personas/{alice_main.id}/rename",
            data={"display_name": "Personal search"},
            follow_redirects=False,
        )
        assert renamed.status_code == 303
        created = alice_client.post(
            "/personas",
            data={"display_name": "Career change"},
            follow_redirects=False,
        )
        assert created.status_code == 303
        alice_personas = container.personas.list_for_account(alice.id)
        personal = next(item for item in alice_personas if item.name == "Personal search")
        career_change = next(item for item in alice_personas if item.name == "Career change")

        # Creation makes the new persona active. Its workspace is independent.
        career_start = alice_client.post("/profile/start", follow_redirects=False)
        career_workspace = career_start.headers["location"].rsplit("/", 1)[-1]
        switched = alice_client.post(
            f"/personas/{personal.id}/switch",
            follow_redirects=False,
        )
        assert switched.status_code == 303
        personal_start = alice_client.post("/profile/start", follow_redirects=False)
        personal_workspace = personal_start.headers["location"].rsplit("/", 1)[-1]
        assert alice_client.get(f"/profile/{personal_workspace}").status_code == 200
        assert alice_client.get(f"/profile/{career_workspace}").status_code == 404

        # A second registration is a separate account, not a shared persona.
        assert register(bob_client, "bob@example.com", "Bob").status_code == 303
        bob = next(item for item in container.accounts.list_accounts() if item.id != alice.id)
        (bob_main,) = container.personas.list_for_account(bob.id)
        bob_client.post("/personas", data={"display_name": "Student"})
        bob_page = bob_client.get("/personas")
        alice_page = alice_client.get("/personas")
        assert "Student" in bob_page.text
        assert "Personal search" not in bob_page.text
        assert "Career change" not in bob_page.text
        assert "Personal search" in alice_page.text
        assert "Career change" in alice_page.text
        assert "Student" not in alice_page.text
        assert 'class="persona-identity"' in alice_page.text

        # Persona switches need only the authenticated account session. A
        # persona belonging to another account cannot be selected or inspected.
        refused_switch = bob_client.post(
            f"/personas/{career_change.id}/switch",
            follow_redirects=False,
        )
        assert refused_switch.status_code == 400
        assert "Persona not found" in refused_switch.text
        assert bob_client.get(f"/profile/{career_workspace}").status_code == 404
        assert bob_client.get(f"/profile/{personal_workspace}").status_code == 404
        assert container.personas.get(bob_main.id, account_id=alice.id) is None


def test_persona_names_are_unique_per_account_and_five_slot_limit_is_enforced(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        register(client, "owner@example.com", "Owner")
        created = client.post("/personas", data={"display_name": "Research"})
        duplicate = client.post(
            "/personas",
            data={"display_name": "  research  "},
        )
        assert created.status_code == 200
        assert duplicate.status_code == 400
        assert "already in use for this account" in duplicate.text

        for name in ("Technical", "Leadership", "Wildcard"):
            assert client.post("/personas", data={"display_name": name}).status_code == 200
        refused = client.post("/personas", data={"display_name": "Sixth"})

    (account,) = container.accounts.list_accounts()
    assert refused.status_code == 400
    assert "up to 5 personas" in refused.text
    assert len(container.personas.list_for_account(account.id)) == 5


def test_final_persona_cannot_be_deleted(tmp_path: Path) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        register(client, "owner@example.com", "Owner")
        (account,) = container.accounts.list_accounts()
        (only_persona,) = container.personas.list_for_account(account.id)
        refused = client.post(
            f"/personas/{only_persona.id}/delete",
            data={"confirm_delete": "true"},
            follow_redirects=False,
        )

    assert refused.status_code == 303
    assert "keep+at+least+one+persona" in refused.headers["location"]
    assert container.personas.list_for_account(account.id) == [only_persona]


def test_registration_mode_controls_accounts_not_persona_slots(tmp_path: Path) -> None:
    open_container = ApplicationContainer(account_settings(tmp_path / "open"))
    open_app = create_app(open_container, data_directory=tmp_path / "open-data")
    with TestClient(open_app) as client:
        assert register(client, "open@example.com", "Open user").status_code == 303
        assert client.get("/personas").status_code == 200
        assert client.post("/personas", data={"display_name": "Second"}).status_code == 200
    assert open_container.accounts.count() == 1

    disabled_container = ApplicationContainer(
        account_settings(tmp_path / "disabled", registration_mode="disabled")
    )
    disabled_app = create_app(
        disabled_container,
        data_directory=tmp_path / "disabled-data",
    )
    with TestClient(disabled_app) as client:
        page = client.get("/register", follow_redirects=False)
        submitted = register(client, "closed@example.com", "Closed user")

    assert page.status_code == 303
    assert page.headers["location"].startswith("/login?")
    assert submitted.status_code == 400
    assert "Account registration is disabled" in submitted.text
    assert disabled_container.accounts.count() == 0
