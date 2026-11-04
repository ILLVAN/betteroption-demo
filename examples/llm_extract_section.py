"""Interactive first LLM extraction test for one profile section."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from betteroption.container import ApplicationContainer  # noqa: E402
from betteroption.profile import CandidateProfile, ProfileSection  # noqa: E402
from betteroption.providers import ProfileExtractionError  # noqa: E402
from betteroption.review import save_profile  # noqa: E402
from betteroption.runtime import print_virtual_environment_warning  # noqa: E402
from betteroption.terminal import LEVEL_LABELS, read_multiline, review_profile  # noqa: E402


def main() -> int:
    load_dotenv()
    print_virtual_environment_warning()

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing. Copy .env.example to .env and add the key locally.")
        return 2

    print("WorkLifeBalance - first live free-text extraction")
    print("What are you looking for professionally?")
    print("Describe roles, responsibilities, and the direction in which you want to grow.")
    print()
    answer = read_multiline()
    if not answer:
        print("No input received.")
        return 2

    extractor = ApplicationContainer().profile_extractor()
    print(f"\nAnalyzing with {extractor.model}...")
    try:
        extraction = extractor.extract(ProfileSection.DIRECTION, answer)
    except ProfileExtractionError as exc:
        print(f"\nAPI request failed: {exc}")
        return 1
    combined_answer = answer

    if extraction.follow_up_question:
        print(f"\nMost important follow-up: {extraction.follow_up_question}")
        clarification = input("Answer (empty = later): ").strip()
        if clarification:
            combined_answer = (
                f"{answer}\n\n"
                f"Follow-up question: {extraction.follow_up_question}\n"
                f"Answer: {clarification}"
            )
            print("\nUpdating the extraction...")
            try:
                extraction = extractor.extract(ProfileSection.DIRECTION, combined_answer)
            except ProfileExtractionError as exc:
                print(f"\nAPI request failed: {exc}")
                return 1

    profile_facts = extraction.to_profile_facts(ProfileSection.DIRECTION)
    profile = CandidateProfile(
        raw_sections={ProfileSection.DIRECTION: combined_answer},
        facts=profile_facts,
    )
    if extraction.follow_up_question:
        profile.unresolved_questions.append(extraction.follow_up_question)

    print("\nWhat I understood")
    print(f"Summary: {extraction.summary}\n")
    if not profile_facts:
        print("No reliable facts were identified yet.")

    for item in profile_facts:
        print(f"[{LEVEL_LABELS[item.level]}] {item.key} = {item.value}")
        print(f'  Evidence: "{item.source.text}"')
        print(f"  Confidence: {item.confidence.value}; confirmation required: yes\n")

    print(f"\n{len(profile_facts)} fact(s) await your review.")
    review_profile(profile)

    path = save_profile(profile)
    confirmed = len(profile.confirmed_facts)
    rejected = len([fact for fact in profile.facts if fact.evidence_status.value == "rejected"])
    pending = len(profile.pending_facts)
    print("Review completed")
    print(f"- confirmed: {confirmed}")
    print(f"- rejected: {rejected}")
    print(f"- pending: {pending}")
    print(f"- saved to: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
