from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import func, select

from betteroption.accounts import AccountRepository, RegistrationMode
from betteroption.database import Database, _migration_config
from betteroption.employer_reputation import (
    EmployerReputationError,
    EmployerReputationRatingRow,
    EmployerReputationRepository,
    normalize_employer_name,
    resolved_employer_name,
)
from betteroption.personas import PersonaRepository


PASSWORD = "correct horse battery staple"


def _account_with_persona(
    database: Database,
    email: str,
    name: str,
):
    accounts = AccountRepository(database)
    personas = PersonaRepository(database)
    account = accounts.create(
        email,
        name,
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = personas.create(account.id, "Main", maximum_personas=5)
    return account, persona


def test_employer_name_normalization_is_stable_without_guessing_entities() -> None:
    assert normalize_employer_name("  OTHERMO   G.m.b.H.  ") == (
        "OTHERMO G.m.b.H.",
        "othermo gmbh",
    )
    assert normalize_employer_name("othermo GmbH")[1] == "othermo gmbh"
    assert normalize_employer_name("Example AG")[1] != normalize_employer_name("Example GmbH")[1]
    assert (
        normalize_employer_name("A&B Products")[1] == normalize_employer_name("A & B Products")[1]
    )
    with pytest.raises(EmployerReputationError, match="required"):
        normalize_employer_name("   ")
    with pytest.raises(EmployerReputationError, match="control"):
        normalize_employer_name("Example\u0000Company")


def test_placeholder_and_portal_host_employers_cannot_share_private_ratings() -> None:
    for value in (
        "Unknown",
        "Traceable Company",
        "External source",
        "Job Portal",
        "jobs.siemens.com",
    ):
        assert resolved_employer_name(value) is None

    assert resolved_employer_name("Siemens AG") == "Siemens AG"


def test_rating_follows_normalized_employer_and_keeps_zero_distinct_from_unrated(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'ratings.db').as_posix()}")
    account, persona = _account_with_persona(database, "owner@example.com", "Owner")
    ratings = EmployerReputationRepository(database)

    first = ratings.set_rating(
        persona.id,
        "othermo GmbH",
        3,
        account_id=account.id,
    )
    assert first is not None
    assert first.stars == 3
    assert (
        ratings.get(
            persona.id,
            " OTHERMO G.m.b.H. ",
            account_id=account.id,
        )
        == first
    )

    updated = ratings.set_rating(
        persona.id,
        "Othermo GmbH",
        5,
        account_id=account.id,
    )
    assert updated is not None
    assert updated.id == first.id
    assert updated.stars == 5
    assert len(ratings.list_for_persona(persona.id, account_id=account.id)) == 1

    blocked = ratings.set_rating(
        persona.id,
        "othermo GmbH",
        0,
        account_id=account.id,
    )
    assert blocked.stars == 0
    assert ratings.get(persona.id, "othermo GmbH", account_id=account.id).stars == 0
    assert ratings.clear(persona.id, "othermo GmbH", account_id=account.id)
    assert ratings.get(persona.id, "othermo GmbH", account_id=account.id) is None


def test_ratings_are_isolated_by_persona_and_account(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'isolation.db').as_posix()}")
    alice, alice_persona = _account_with_persona(database, "alice@example.com", "Alice")
    bob, bob_persona = _account_with_persona(database, "bob@example.com", "Bob")
    alice_second = PersonaRepository(database).create(
        alice.id,
        "Career change",
        maximum_personas=5,
    )
    ratings = EmployerReputationRepository(database)

    ratings.set_rating(alice_persona.id, "Example SE", 5, account_id=alice.id)
    ratings.set_rating(alice_second.id, "Example SE", 2, account_id=alice.id)
    ratings.set_rating(bob_persona.id, "Example SE", 1, account_id=bob.id)

    assert ratings.get(alice_persona.id, "example s.e.", account_id=alice.id).stars == 5
    assert ratings.get(alice_second.id, "Example SE", account_id=alice.id).stars == 2
    assert ratings.get(bob_persona.id, "Example SE", account_id=bob.id).stars == 1
    with pytest.raises(EmployerReputationError, match="Persona not found"):
        ratings.get(alice_persona.id, "Example SE", account_id=bob.id)
    with pytest.raises(EmployerReputationError, match="Persona not found"):
        ratings.set_rating(
            bob_persona.id,
            "Example SE",
            4,
            account_id=alice.id,
        )


def test_rating_validation_export_and_owner_cascade(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'lifecycle.db').as_posix()}")
    accounts = AccountRepository(database)
    account, persona = _account_with_persona(database, "export@example.com", "Export")
    ratings = EmployerReputationRepository(database)
    rating = ratings.set_rating(persona.id, "Calm Machines AG", 4, account_id=account.id)
    assert rating is not None

    for invalid in (-1, 6, True, 2.5):
        with pytest.raises(EmployerReputationError, match="0 to 5"):
            ratings.set_rating(
                persona.id,
                "Calm Machines AG",
                invalid,  # type: ignore[arg-type]
                account_id=account.id,
            )

    exported = json.loads(accounts.export_json(account.id))
    assert len(exported["employer_reputation_ratings"]) == 1
    exported_rating = exported["employer_reputation_ratings"][0]
    assert exported_rating["id"] == str(rating.id)
    assert exported_rating["persona_id"] == str(persona.id)
    assert exported_rating["employer_key"] == "calm machines ag"
    assert exported_rating["employer_name"] == "Calm Machines AG"
    assert exported_rating["stars"] == 4
    assert exported_rating["created_at"]
    assert exported_rating["updated_at"]

    assert accounts.delete_account(account.id)
    with database.session_factory() as session:
        remaining = session.scalar(select(func.count(EmployerReputationRatingRow.id)))
    assert remaining == 0


def test_employer_reputation_migration_follows_application_drafts() -> None:
    script = ScriptDirectory.from_config(_migration_config("sqlite:///:memory:"))
    revision = script.get_revision("0023_employer_reputation_ratings")
    assert revision is not None
    assert revision.down_revision == "0022_application_draft_slots"

    scoring = script.get_revision("0025_employer_reputation_scoring")
    assert scoring is not None
    assert scoring.down_revision == "0024_posting_date_evidence"
