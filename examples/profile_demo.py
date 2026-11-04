"""First executable WorkLifeBalance profile example.

This intentionally does not call an LLM yet. It demonstrates the exact typed
output that the extraction layer must produce from the guided conversation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from betteroption.profile import (  # noqa: E402
    CandidateProfile,
    Compensation,
    Confidence,
    EvidenceStatus,
    LocationPreference,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    TravelConstraint,
    TravelMode,
    WorkModel,
)


RAW_SECTIONS = {
    ProfileSection.DIRECTION: (
        "I am interested in data visualization or accessibility engineering, "
        "but not a quota-carrying sales role."
    ),
    ProfileSection.LOCATION_MOBILITY: (
        "From Leipzig, at most 40 minutes by public transit or 25 minutes by bicycle. "
        "Two office days, otherwise remote."
    ),
    ProfileSection.MUST_HAVES: (
        "At least EUR 58,000, a direct employer contract, and no weekly business travel."
    ),
    ProfileSection.PREFERENCES: (
        "A 32-hour week, transparent salary bands, public-interest products, and a learning budget."
    ),
    ProfileSection.EXCLUSIONS: (
        "No management-only role, no outbound sales, and no permanent on-call rotation."
    ),
}


def fact(
    key: str,
    value: str | int | float | bool | list[str],
    level: RequirementLevel,
    section: ProfileSection,
    quote: str,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.EXPLICIT,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=quote),
    )


def build_demo_profile() -> CandidateProfile:
    return CandidateProfile(
        raw_sections=RAW_SECTIONS,
        location=LocationPreference(
            origin_label="Leipzig",
            origin_precision="city",
            travel_constraints=[
                TravelConstraint(mode=TravelMode.TRANSIT, maximum_minutes_one_way=40),
                TravelConstraint(mode=TravelMode.BICYCLE, maximum_minutes_one_way=25),
            ],
        ),
        work_model=WorkModel(
            maximum_office_days_per_week=2,
            minimum_remote_days_per_week=3,
            target_weekly_hours=32,
        ),
        compensation=Compensation(
            minimum_gross_annual=58_000,
            minimum_level=RequirementLevel.MUST_HAVE,
        ),
        facts=[
            fact(
                "role.families",
                ["data visualization", "accessibility engineering"],
                RequirementLevel.PREFERENCE,
                ProfileSection.DIRECTION,
                "data visualization or accessibility engineering",
            ),
            fact(
                "role.quota_carrying_sales",
                True,
                RequirementLevel.EXCLUSION,
                ProfileSection.DIRECTION,
                "not a quota-carrying sales role",
            ),
            fact(
                "employment.direct_contract",
                True,
                RequirementLevel.MUST_HAVE,
                ProfileSection.MUST_HAVES,
                "a direct employer contract",
            ),
            fact(
                "travel.regular",
                True,
                RequirementLevel.EXCLUSION,
                ProfileSection.MUST_HAVES,
                "no weekly business travel",
            ),
            fact(
                "compensation.transparent_bands",
                True,
                RequirementLevel.PREFERENCE,
                ProfileSection.PREFERENCES,
                "transparent salary bands",
            ),
            fact(
                "role.people_management_only",
                True,
                RequirementLevel.EXCLUSION,
                ProfileSection.EXCLUSIONS,
                "No management-only role",
            ),
            fact(
                "role.outbound_sales",
                True,
                RequirementLevel.EXCLUSION,
                ProfileSection.EXCLUSIONS,
                "no outbound sales",
            ),
        ],
    )


if __name__ == "__main__":
    profile = build_demo_profile()
    print(profile.model_dump_json(indent=2))
    print("\nReview tray:")
    print(f"- {len(profile.confirmed_facts)} confirmed")
    print(f"- {len(profile.pending_facts)} awaiting user confirmation")
