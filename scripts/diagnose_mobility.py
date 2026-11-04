"""Run one privacy-scoped mobility provider check without profile or database data."""

from __future__ import annotations

import argparse
from zoneinfo import ZoneInfo

from betteroption.container import ApplicationContainer
from betteroption.mobility import TravelQuery, _next_peak_departure
from betteroption.profile import TravelMode
from betteroption.settings import Settings


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--origin", required=True, help="Explicit route origin")
    command.add_argument("--destination", required=True, help="Explicit route destination")
    command.add_argument(
        "--mode",
        choices=[mode.value for mode in TravelMode],
        default=TravelMode.TRANSIT.value,
    )
    return command


def main() -> int:
    arguments = parser().parse_args()
    mode = TravelMode(arguments.mode)
    departure = _next_peak_departure() if mode in {TravelMode.TRANSIT, TravelMode.CAR} else None
    provider = ApplicationContainer(
        Settings(database_url="sqlite:///:memory:")
    ).travel_time_provider()
    configured = getattr(provider, "providers", [provider])
    print("Configured provider order: " + " -> ".join(item.name for item in configured))
    estimate = provider.estimate(
        TravelQuery(
            origin=arguments.origin,
            destination=arguments.destination,
            mode=mode,
            departure_at=departure,
        )
    )

    print(f"Provider: {estimate.provider}")
    print(f"Status: {estimate.status.value}")
    print(f"Duration: {estimate.duration_minutes or 'unknown'} min")
    if departure:
        local = departure.astimezone(ZoneInfo("Europe/Berlin"))
        print(f"Comparison departure: {local.isoformat()}")
    if estimate.message:
        print(f"Message: {estimate.message}")
    if estimate.origin_resolved:
        print(f"Resolved origin: {estimate.origin_resolved}")
    if estimate.destination_resolved:
        print(f"Resolved destination: {estimate.destination_resolved}")
    if estimate.attempts:
        print("Diagnostics:")
        for attempt in estimate.attempts:
            print(f"- {attempt}")
    return 0 if estimate.duration_minutes is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
