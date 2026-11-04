"""Reusable terminal UI helpers for local profile alpha workflows."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from .profile import (
    CandidateProfile,
    EvidenceStatus,
    ProfileFact,
    RequirementLevel,
    ReviewAction,
)
from .review import apply_review


LEVEL_LABELS = {
    RequirementLevel.MUST_HAVE: "MUST HAVE",
    RequirementLevel.PREFERENCE: "PREFERENCE",
    RequirementLevel.EXCLUSION: "EXCLUSION",
    RequirementLevel.OPEN: "OPEN",
}

SAFE_BULK_CONFIRM_LEVELS = {
    RequirementLevel.PREFERENCE,
    RequirementLevel.OPEN,
}


def read_multiline(*, commands: set[str] | None = None) -> str:
    """Read natural multi-line terminal input until the first empty line."""

    supported_commands = commands or set()
    print("You can type or paste multiple lines.")
    print("Finish your answer with an additional empty line.\n")
    lines: list[str] = []
    while True:
        prompt = "> " if not lines else "| "
        line = input(prompt)
        normalized = line.strip().lower()
        if not lines and normalized in supported_commands:
            return normalized
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines).strip()


def ask_level() -> RequirementLevel:
    choices = {
        "1": RequirementLevel.MUST_HAVE,
        "2": RequirementLevel.PREFERENCE,
        "3": RequirementLevel.EXCLUSION,
        "4": RequirementLevel.OPEN,
    }
    while True:
        print("  1 = Must have, 2 = Preference, 3 = Exclusion, 4 = Open")
        choice = input("  New category: ").strip()
        if choice in choices:
            return choices[choice]
        print("  Enter 1, 2, 3, or 4.")


def edit_fact_value(profile: CandidateProfile, fact: ProfileFact) -> None:
    """Edit a value and explicitly verify that its old category still applies."""

    value = input("   New value: ").strip()
    if not value:
        raise ValueError("The value cannot be empty.")
    previous_level = fact.level
    apply_review(profile, fact.id, ReviewAction.EDIT_VALUE, new_value=value)
    keep_level = (
        input(f"   Category is still {LEVEL_LABELS[previous_level]}. Keep it? [Y/n]: ")
        .strip()
        .lower()
    )
    if keep_level not in {"", "y", "yes"}:
        level = ask_level()
        apply_review(profile, fact.id, ReviewAction.CHANGE_LEVEL, new_level=level)


def _confirm_safe_remaining(profile: CandidateProfile, facts: list[ProfileFact]) -> int:
    safe_facts = [
        fact for fact in facts if fact.needs_confirmation and fact.level in SAFE_BULK_CONFIRM_LEVELS
    ]
    if not safe_facts:
        print("   No pending Preference or Open facts can be bulk-confirmed.")
        return 0
    answer = (
        input(f"   Confirm {len(safe_facts)} remaining Preference/Open fact(s)? [y/N]: ")
        .strip()
        .lower()
    )
    if answer not in {"y", "yes"}:
        print("   Bulk confirmation cancelled.")
        return 0
    for fact in safe_facts:
        apply_review(profile, fact.id, ReviewAction.CONFIRM)
    print(f"   Confirmed {len(safe_facts)} safe fact(s) in bulk.\n")
    return len(safe_facts)


def review_profile(
    profile: CandidateProfile,
    fact_ids: Iterable[UUID] | None = None,
) -> None:
    """Review pending facts, optionally limited to one extraction batch."""

    allowed_ids = set(fact_ids) if fact_ids is not None else None
    facts = [
        fact
        for fact in profile.facts
        if fact.needs_confirmation and (allowed_ids is None or fact.id in allowed_ids)
    ]

    if not facts:
        print("No pending facts need review.")
        return

    print("\nReview Tray")
    print(
        "c = confirm, e = edit value, l = change level, r = reject, "
        "s = skip for now, a = accept all safe remaining\n"
    )

    for index, fact in enumerate(facts, start=1):
        if not fact.needs_confirmation:
            continue
        print(f"{index}. [{LEVEL_LABELS[fact.level]}] {fact.key} = {fact.value}")
        print(f'   Evidence: "{fact.source.text}"')
        while True:
            action = input("   Action [c/e/l/r/s/a]: ").strip().lower()
            if action == "c":
                apply_review(profile, fact.id, ReviewAction.CONFIRM)
                print("   Confirmed\n")
                break
            if action == "e":
                try:
                    edit_fact_value(profile, fact)
                except ValueError as exc:
                    print(f"   {exc}")
                    continue
                print("   Edited and confirmed\n")
                break
            if action == "l":
                level = ask_level()
                apply_review(profile, fact.id, ReviewAction.CHANGE_LEVEL, new_level=level)
                print("   Level changed and confirmed\n")
                break
            if action == "r":
                apply_review(profile, fact.id, ReviewAction.REJECT)
                print("   Rejected\n")
                break
            if action == "s":
                print("   Left pending for later review\n")
                break
            if action == "a":
                _confirm_safe_remaining(profile, facts[index - 1 :])
                if not fact.needs_confirmation:
                    break
                print("   This hard condition still requires an individual decision.")
                continue
            print("   Enter c, e, l, r, s, or a.")


def edit_confirmed_profile(profile: CandidateProfile) -> None:
    """Interactively edit confirmed facts in a previously saved profile."""

    query = ""
    while True:
        facts = [
            fact
            for fact in profile.facts
            if fact.evidence_status == EvidenceStatus.CONFIRMED
            and (not query or query in fact.key.lower() or query in str(fact.value).lower())
        ]
        print("\nConfirmed profile facts")
        if query:
            print(f'Filter: "{query}"')
        for index, fact in enumerate(facts, start=1):
            print(f"{index}. [{LEVEL_LABELS[fact.level]}] {fact.key} = {fact.value}")
        choice = input("\nFact number, /find TEXT, /all, or q to save and exit: ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            return
        if choice.startswith("/find "):
            query = choice.removeprefix("/find ").strip()
            continue
        if choice == "/all":
            query = ""
            continue
        direct_action = choice if len(facts) == 1 and choice in {"e", "l", "r"} else None
        if direct_action is None and (not choice.isdigit() or not 1 <= int(choice) <= len(facts)):
            print("Enter a listed fact number, /find TEXT, /all, or q.")
            continue

        fact = facts[0] if direct_action else facts[int(choice) - 1]
        print(f"Selected: [{LEVEL_LABELS[fact.level]}] {fact.key} = {fact.value}")
        action = direct_action or (
            input("Action [e = edit value, l = change level, r = reject, b = back]: ")
            .strip()
            .lower()
        )
        if action == "e":
            try:
                edit_fact_value(profile, fact)
            except ValueError as exc:
                print(exc)
        elif action == "l":
            apply_review(
                profile,
                fact.id,
                ReviewAction.CHANGE_LEVEL,
                new_level=ask_level(),
            )
        elif action == "r":
            confirmation = input("Reject this fact? [y/N]: ").strip().lower()
            if confirmation in {"y", "yes"}:
                apply_review(profile, fact.id, ReviewAction.REJECT)
        elif action != "b":
            print("Enter e, l, r, or b.")
