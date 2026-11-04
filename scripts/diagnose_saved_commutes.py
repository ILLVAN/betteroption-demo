"""Explain every commute stored in the latest local match run without new API calls."""

from __future__ import annotations

from betteroption.container import ApplicationContainer


def main() -> int:
    container = ApplicationContainer()
    workspace = container.workspaces.latest()
    if workspace is None:
        print("No Compass workspace exists in the configured database.")
        return 2
    run = container.results.latest_run(workspace.id)
    if run is None:
        print("No saved Matching run exists for the current Compass.")
        return 2

    print(f"Matching run: {run.id} ({run.algorithm_version})")
    print(f"Stored results: {len(run.results)}")
    for item in run.results:
        print()
        print(f"{item.job.company} — {item.job.title}")
        if not item.result.commutes:
            print("  No commute constraint was evaluated for this job.")
            continue
        for commute in item.result.commutes:
            estimate = commute.estimate
            duration = (
                f"{estimate.duration_minutes} min"
                if estimate.duration_minutes is not None
                else "unknown"
            )
            print(
                f"  {commute.mode.value}: {estimate.status.value} via "
                f"{estimate.provider} · {duration}"
            )
            print(f"  Query: {commute.origin} -> {commute.destination}")
            if estimate.message:
                print(f"  Message: {estimate.message}")
            for attempt in estimate.attempts:
                print(f"  - {attempt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
