from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.accounts import RegistrationMode
from betteroption.container import ApplicationContainer
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.profile_repository import ConversationRole
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.web import create_app


PASSWORD = "correct horse battery staple"


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v072f-export.db').as_posix()}",
            auth_mode="accounts",
            registration_mode="open",
            background_worker_enabled=False,
            employer_homepage_research=False,
        )
    )


def _session(role: str, *, include_private_history: bool = False):
    session = new_session()
    session.profile.facts = [
        ProfileFact(
            key="role.target",
            value=role,
            level=RequirementLevel.MUST_HAVE,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(section=ProfileSection.DIRECTION, text=role),
            user_note="Keep the role hands-on.",
        )
    ]
    if include_private_history:
        session.profile.raw_sections[ProfileSection.DIRECTION] = (
            "Long raw answer that belongs to operational history, not the portable file."
        )
        session.profile.facts.append(
            ProfileFact(
                key="role.rejected",
                value="Historical rejected proposal",
                level=RequirementLevel.OPEN,
                evidence_status=EvidenceStatus.REJECTED,
                confidence=Confidence.LOW,
                source=SourceExcerpt(
                    section=ProfileSection.DIRECTION,
                    text="Historical rejected proposal",
                ),
            )
        )
    return session


def test_portable_export_contains_only_account_personas_and_current_compasses(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    account = container.accounts.create(
        "portable@example.com",
        "Portable Person",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    main = container.personas.create(account.id, "Main", maximum_personas=5)
    quiet = container.personas.create(account.id, "Quiet search", maximum_personas=5)
    no_compass = container.personas.create(account.id, "Later", maximum_personas=5)
    container.workspaces.create(
        _session("Historical role", include_private_history=True),
        account_id=account.id,
        persona_id=main.id,
    )
    current = container.workspaces.create(
        _session("Embedded software engineer"),
        account_id=account.id,
        persona_id=main.id,
    )
    container.workspaces.create(
        _session("Technical writer"),
        account_id=account.id,
        persona_id=quiet.id,
    )
    container.workspaces.add_message(
        current.id,
        ConversationRole.USER,
        "Private conversation history must stay out of the portable profile.",
        section=ProfileSection.DIRECTION,
    )

    portable = json.loads(container.accounts.export_portable_json(account.id))
    complete_internal = json.loads(container.accounts.export_json(account.id))

    assert set(portable) == {"format", "exported_at", "account", "personas"}
    assert portable["format"] == "worklifebalance-portable-profile-v1"
    assert set(portable["account"]) == {
        "email",
        "display_name",
        "email_verified_at",
        "created_at",
        "updated_at",
        "legal_documents",
    }
    personas = {item["name"]: item for item in portable["personas"]}
    assert set(personas) == {"Main", "Quiet search", "Later"}
    assert personas["Main"]["compass"]["statements"] == [
        {
            "section": "direction",
            "key": "role.target",
            "value": "Embedded software engineer",
            "importance": "must_have",
            "note": "Keep the role hands-on.",
        }
    ]
    assert personas["Quiet search"]["compass"]["statements"][0]["value"] == ("Technical writer")
    assert personas["Later"]["compass"] is None

    serialized = json.dumps(portable)
    for internal_key in (
        "id",
        "session_json",
        "raw_sections",
        "conversation_messages",
        "background_tasks",
        "provider_operations",
        "match_runs",
        "match_results",
        "explore_searches",
        "saved_job_access",
    ):
        assert f'"{internal_key}"' not in serialized
    assert "Historical role" not in serialized
    assert "Historical rejected proposal" not in serialized
    assert "Private conversation history" not in serialized
    assert complete_internal["conversation_messages"]
    assert len(complete_internal["workspaces"]) == 3
    assert no_compass.id


def test_account_download_uses_portable_profile_and_disables_caching(tmp_path: Path) -> None:
    container = _container(tmp_path)
    account = container.accounts.create(
        "download@example.com",
        "Download Person",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    container.workspaces.create(
        _session("Systems engineer"),
        account_id=account.id,
        persona_id=persona.id,
    )
    session = container.accounts.create_session(account, ttl=timedelta(days=1))

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        client.cookies.set("betteroption_session", session.token)
        response = client.get("/account/export")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="worklifebalance-profile-export.json"'
    )
    assert response.json()["format"] == "worklifebalance-portable-profile-v1"
    assert "workspaces" not in response.json()
