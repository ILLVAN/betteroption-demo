"""Extract job text and run the first deterministic BetterOption matcher."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from betteroption.container import ApplicationContainer  # noqa: E402
from betteroption.job_corpus import JobCorpusError, JobCorpusService, JobImportResult  # noqa: E402
from betteroption.jobs import JobPosting, load_job  # noqa: E402
from betteroption.matching import (  # noqa: E402
    MatchDisposition,
    MatchOutcome,
    match_jobs,
    save_match_run,
)
from betteroption.providers import JobExtractionError  # noqa: E402
from betteroption.runtime import print_virtual_environment_warning  # noqa: E402
from betteroption.session import latest_session_path, load_session  # noqa: E402
from betteroption.settings import Settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session",
        default="latest",
        metavar="PATH_OR_LATEST",
        help="Profile session to use; defaults to the newest local checkpoint.",
    )
    parser.add_argument(
        "--job-url",
        action="append",
        default=[],
        help="Public job-advertisement URL to fetch and extract. Repeat for multiple URLs.",
    )
    parser.add_argument(
        "--corpus",
        action="store_true",
        help="Match all live corpus jobs, refreshing links older than 24 hours.",
    )
    parser.add_argument(
        "--refresh-corpus",
        action="store_true",
        help="Force a URL recheck for every corpus record before matching live jobs.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy database URL; defaults to BETTEROPTION_DATABASE_URL or local SQLite.",
    )
    return parser.parse_args()


def load_profile_session(path_or_latest: str):
    path = latest_session_path() if path_or_latest.lower() == "latest" else Path(path_or_latest)
    if path is None:
        raise FileNotFoundError("no saved profile session was found")
    return load_session(path)


def load_sample_jobs() -> list[JobPosting]:
    directory = Path(__file__).parent / "sample_jobs"
    return [load_job(path) for path in sorted(directory.glob("*.json"))]


def print_import_result(url: str, result: JobImportResult) -> None:
    label = result.kind.value.upper()
    if result.job is None:
        print(f"[{label}] {url}: {result.message}")
        return
    print(f"[{label}] {result.job.title} - {result.job.company}")
    print(f"  URL: {result.job.source_url}")
    if result.source_snapshot_path:
        print(f"  Source snapshot: {result.source_snapshot_path}")
    if result.used_cached_extraction:
        print("  LLM extraction: reused cached canonical revision")
    else:
        print("  LLM extraction: created a canonical revision")
    if result.record:
        print(f"  Corpus record: {result.record.id} | revisions: {result.record.revision_count}")
    for warning in result.job.extraction_warnings:
        print(f"  Extraction warning: {warning}")


def import_job_urls(urls: list[str], service: JobCorpusService) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for url in urls:
        try:
            result = service.import_url(url)
        except (JobCorpusError, JobExtractionError) as exc:
            print(f"[FAILED] {url}: {exc}")
            continue
        print_import_result(url, result)
        if result.job is not None:
            jobs.append(result.job)

    unique_jobs: dict[str, JobPosting] = {}
    for job in jobs:
        if job.content_hash in unique_jobs:
            print(f"Skipped duplicate content: {job.source_url}")
        else:
            unique_jobs[job.content_hash] = job
    return list(unique_jobs.values())


def build_corpus_service(database_url: str | None, model: str) -> JobCorpusService:
    overrides = {"openai_model": model}
    if database_url:
        overrides["database_url"] = database_url
    settings = Settings(**overrides)
    return ApplicationContainer(settings).job_corpus_service()


def print_result(position: int, job: JobPosting, result) -> None:
    label = {
        MatchDisposition.TOP: "TOP MATCH",
        MatchDisposition.STRETCH: "STRETCH",
        MatchDisposition.BLOCKED: "BLOCKED",
    }[result.disposition]
    print("\n" + "=" * 78)
    print(f"{position}. [{label}] {job.title} - {job.company}")
    print(
        f"Fit score: {result.score}/100 | Hard-evidence coverage: "
        f"{result.hard_evidence_coverage}% | Location: {job.location}"
    )
    print(job.summary)

    decisive = [
        reason
        for reason in result.reasons
        if reason.outcome
        in {
            MatchOutcome.VIOLATED,
            MatchOutcome.SATISFIED,
            MatchOutcome.SUPPORTING,
        }
    ]
    for reason in decisive[:8]:
        marker = {
            MatchOutcome.VIOLATED: "!",
            MatchOutcome.SATISFIED: "+",
            MatchOutcome.SUPPORTING: "+",
        }[reason.outcome]
        print(f"{marker} {reason.profile_key}: {reason.profile_value}")
        for quote in reason.evidence_quotes[:2]:
            print(f'  Evidence: "{quote}"')

    unknown_count = sum(reason.outcome == MatchOutcome.UNKNOWN for reason in result.reasons)
    if unknown_count:
        print(f"? {unknown_count} hard condition(s) are not evidenced by the advertisement.")
    if result.matched_required_skills:
        print("Matched required skills: " + ", ".join(result.matched_required_skills))
    if result.missing_required_skills:
        print("Unproven required skills: " + ", ".join(result.missing_required_skills))
    if result.job_url:
        print(f"Job URL: {result.job_url}")
        print(
            f"URL status: {result.url_status.value.replace('_', ' ')} "
            f"(HTTP {result.url_http_status}) "
            f"at {result.url_verified_at.isoformat()}"
        )
    else:
        print(f"Source: fictional built-in sample ({job.source_name}); no live URL")


def main() -> int:
    args = parse_args()
    load_dotenv()
    print_virtual_environment_warning()

    try:
        session = load_profile_session(args.session)
        model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
        if args.job_url or args.corpus or args.refresh_corpus:
            service = build_corpus_service(args.database_url, model)
            imported_jobs = import_job_urls(args.job_url, service)
            if args.refresh_corpus:
                print("\nRefreshing every corpus URL...")
                for record, result in zip(
                    service.repository.list_records(),
                    service.refresh_all(),
                    strict=True,
                ):
                    print_import_result(record.canonical_url, result)
            jobs = (
                service.jobs_ready_for_presentation()
                if args.corpus or args.refresh_corpus
                else imported_jobs
            )
        else:
            jobs = load_sample_jobs()
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        JobExtractionError,
        JobCorpusError,
    ) as exc:
        print(f"Could not prepare the match run: {exc}")
        return 2

    run = match_jobs(session.profile, jobs)
    jobs_by_id = {job.id: job for job in jobs}
    print(f"\nMatched {len(jobs)} job(s) against profile {session.profile.id}.")
    for position, result in enumerate(run.results, start=1):
        print_result(position, jobs_by_id[result.job_id], result)
    path = save_match_run(run)
    print(f"\nMatch run saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
