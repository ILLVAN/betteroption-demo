"""Run the complete resumable WorkLifeBalance profile conversation."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from betteroption.container import ApplicationContainer  # noqa: E402
from betteroption.extraction import SectionExtraction  # noqa: E402
from betteroption.llm import ProfileExtractorPort  # noqa: E402
from betteroption.profile import EvidenceStatus, ProfileSection, RequirementLevel  # noqa: E402
from betteroption.providers import ProfileExtractionError  # noqa: E402
from betteroption.review import MergeResult, save_profile  # noqa: E402
from betteroption.runtime import print_virtual_environment_warning  # noqa: E402
from betteroption.session import (  # noqa: E402
    ProfileSession,
    SessionState,
    complete_section_review,
    definition_for,
    latest_session_path,
    load_session,
    mark_section_skipped,
    new_session,
    next_pending_section,
    next_review_section,
    progress_for,
    record_section_extraction,
    reopen_skipped_sections,
    save_session,
)
from betteroption.terminal import (  # noqa: E402
    LEVEL_LABELS,
    edit_confirmed_profile,
    read_multiline,
    review_profile,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume",
        metavar="PATH_OR_LATEST",
        help="Resume a session JSON file, or use 'latest' for the newest checkpoint.",
    )
    parser.add_argument(
        "--edit-profile",
        action="store_true",
        help="Edit confirmed facts in a saved session, save the changes, and exit.",
    )
    return parser.parse_args()


def resolve_session(resume: str | None) -> ProfileSession:
    if not resume:
        session = new_session()
        print(f"Started a new profile session: {session.id}")
        return session

    path = latest_session_path() if resume.lower() == "latest" else Path(resume)
    if path is None:
        raise FileNotFoundError("no saved profile session was found")
    session = load_session(path)
    print(f"Resumed profile session: {session.id}")
    return session


def print_section(session: ProfileSession, section: ProfileSection) -> None:
    definition = definition_for(section)
    total = len(session.sections)
    position = next(
        index
        for index, progress in enumerate(session.sections, start=1)
        if progress.section == section
    )
    print("\n" + "=" * 72)
    print(f"Section {position}/{total}: {definition.title}")
    print(definition.question)
    print(definition.guidance)
    print(f'Example: "{definition.example}"')
    print("Commands: /skip leaves this section for later; /quit saves and exits.\n")


def extract_with_follow_up(
    extractor: ProfileExtractorPort,
    section: ProfileSection,
    answer: str,
) -> tuple[str, SectionExtraction, bool]:
    extraction = extractor.extract(section, answer)
    combined_answer = answer
    unresolved_follow_up = False

    if extraction.follow_up_question:
        print(f"\nMost important follow-up: {extraction.follow_up_question}")
        clarification = input("Answer (empty = leave unresolved): ").strip()
        if clarification:
            combined_answer = (
                f"{answer}\n\n"
                f"Follow-up question: {extraction.follow_up_question}\n"
                f"Answer: {clarification}"
            )
            print("Updating the extraction...")
            extraction = extractor.extract(section, combined_answer)
            unresolved_follow_up = bool(extraction.follow_up_question)
            if extraction.follow_up_question:
                print(f"Further follow-up deferred: {extraction.follow_up_question}")
        else:
            unresolved_follow_up = True

    return combined_answer, extraction, unresolved_follow_up


def print_extraction(extraction: SectionExtraction, merge: MergeResult) -> None:
    print("\nWhat I understood")
    print(f"Summary: {extraction.summary}\n")
    if not extraction.facts:
        print("No reliable facts were identified in this section.")
    for draft in extraction.facts:
        print(f"[{LEVEL_LABELS[draft.level]}] {draft.key} = {draft.value}")
        print(f'  Evidence: "{draft.source_quote}"')
        print(f"  Confidence: {draft.confidence.value}; confirmation required: yes\n")
    if merge.protected_fact_ids:
        print(
            f"Protected {len(merge.protected_fact_ids)} prior user decision(s) from model changes."
        )


def print_profile_summary(session: ProfileSession) -> None:
    profile = session.profile
    print("\n" + "=" * 72)
    print("Profile summary")
    search_facts = profile.confirmed_search_facts
    for level in RequirementLevel:
        facts = [fact for fact in search_facts if fact.level == level]
        print(f"\n{LEVEL_LABELS[level]} ({len(facts)})")
        for fact in facts:
            print(f"- {fact.key}: {fact.value}")

    evidence = profile.confirmed_candidate_evidence
    print(f"\nCANDIDATE EVIDENCE ({len(evidence)})")
    for fact in evidence:
        print(f"- {fact.key}: {fact.value}")

    rejected = sum(fact.evidence_status == EvidenceStatus.REJECTED for fact in profile.facts)
    print(f"\nRejected proposals: {rejected}")
    print(f"Pending review: {len(profile.pending_facts)}")
    print(f"Unresolved questions: {len(profile.unresolved_questions)}")
    for index, question in enumerate(profile.unresolved_questions, start=1):
        print(f"  {index}. {question}")


def run_session(session: ProfileSession, extractor: ProfileExtractorPort) -> int:
    checkpoint = save_session(session)
    print(f"Checkpoint: {checkpoint}")

    try:
        while True:
            review_section = next_review_section(session)
            if review_section is not None:
                progress = progress_for(session, review_section)
                print(f"\nResuming the Review Tray for: {definition_for(review_section).title}")
                review_profile(session.profile, progress.proposed_fact_ids)
                complete_section_review(session, review_section)
                checkpoint = save_session(session)
                print(f"Section review saved: {checkpoint}")
                continue

            section = next_pending_section(session)
            if section is None:
                if session.state == SessionState.READY_WITH_SKIPS:
                    answer = (
                        input("\nSome sections were skipped. Revisit them now? [Y/n]: ")
                        .strip()
                        .lower()
                    )
                    if answer in {"", "y", "yes"}:
                        reopened = reopen_skipped_sections(session)
                        save_session(session)
                        print(f"Reopened {reopened} skipped section(s).")
                        continue
                if session.profile.pending_facts:
                    answer = (
                        input(
                            f"\n{len(session.profile.pending_facts)} fact(s) remain pending. "
                            "Review them now? [Y/n]: "
                        )
                        .strip()
                        .lower()
                    )
                    if answer in {"", "y", "yes"}:
                        review_profile(session.profile)
                        checkpoint = save_session(session)
                        print(f"Pending review decisions saved: {checkpoint}")
                break

            print_section(session, section)
            answer = read_multiline(commands={"/skip", "/quit"})
            if answer == "/quit":
                checkpoint = save_session(session)
                print(
                    "Session saved. Resume with: python examples\\profile_session.py --resume latest"
                )
                print(f"Checkpoint: {checkpoint}")
                return 0
            if answer == "/skip":
                mark_section_skipped(session, section)
                checkpoint = save_session(session)
                print(f"Section skipped. Checkpoint: {checkpoint}")
                continue
            if not answer:
                print("Please enter an answer, /skip, or /quit.")
                continue

            print(f"Analyzing {definition_for(section).title.lower()} with {extractor.model}...")
            combined_answer, extraction, unresolved = extract_with_follow_up(
                extractor,
                section,
                answer,
            )
            merge = record_section_extraction(
                session,
                section,
                combined_answer,
                extraction,
                unresolved_follow_up=unresolved,
            )
            checkpoint = save_session(session)
            print(f"Extraction checkpoint saved before review: {checkpoint}")
            print_extraction(extraction, merge)
            review_profile(session.profile, progress_for(session, section).proposed_fact_ids)
            complete_section_review(session, section)
            checkpoint = save_session(session)
            print(
                f"Progress: {session.completed_count}/{len(session.sections)} sections completed. "
                f"Checkpoint: {checkpoint}"
            )
    except KeyboardInterrupt:
        checkpoint = save_session(session)
        print("\nInterrupted safely. Your current state was saved.")
        print(f"Resume with: python examples\\profile_session.py --resume {checkpoint}")
        return 130
    except ProfileExtractionError as exc:
        checkpoint = save_session(session)
        print(f"\nAPI request failed: {exc}")
        print(f"Your state is safe at: {checkpoint}")
        return 1

    print_profile_summary(session)
    profile_path = save_profile(session.profile)
    checkpoint = save_session(session)
    if session.state == SessionState.COMPLETED:
        print("\nAll nine profile sections are complete.")
    else:
        print("\nProfile saved with skipped sections. You can resume them later.")
    print(f"Profile: {profile_path}")
    print(f"Session: {checkpoint}")
    return 0


def main() -> int:
    args = parse_args()
    load_dotenv()
    print_virtual_environment_warning()

    try:
        resume = args.resume or ("latest" if args.edit_profile else None)
        session = resolve_session(resume)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Could not resume the profile session: {exc}")
        return 2

    if args.edit_profile:
        edit_confirmed_profile(session.profile)
        profile_path = save_profile(session.profile)
        session_path = save_session(session)
        print_profile_summary(session)
        print(f"\nUpdated profile: {profile_path}")
        print(f"Updated session: {session_path}")
        return 0

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing. Copy .env.example to .env and add the key locally.")
        return 2

    extractor = ApplicationContainer().profile_extractor()
    print("WorkLifeBalance - guided profile session")
    print("Your answers remain in local, git-ignored checkpoint files during this alpha.")
    return run_session(session, extractor)


if __name__ == "__main__":
    raise SystemExit(main())
