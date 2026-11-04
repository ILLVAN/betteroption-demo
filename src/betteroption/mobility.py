"""Provider-backed commute estimates with privacy-aware database caching."""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from statistics import median
from threading import Lock
from typing import Protocol
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select

from .database import Base, Database
from .geography import (
    OfflineGermanPostalCodeIndex,
    OfflinePlaceIndex,
    ResolvedPlace,
    straight_line_distance_km,
)
from .jobs import JobPosting
from .operations import (
    BudgetDecision,
    ProviderBudgetPolicy,
    ProviderOperation,
    ProviderOperationLedger,
    ProviderOperationOutcome,
)
from .provider_permissions import provider_permission_allowed
from .profile import CandidateProfile, ProfileFact, RequirementLevel, StrictModel, TravelMode
from .profile_mobility import mobility_limit_from_fact


_ROUTING_PLACE_INDEX = OfflinePlaceIndex()
_ROUTING_POSTAL_INDEX = OfflineGermanPostalCodeIndex()
_MAX_ROUTED_DESTINATIONS = 12


class CommuteStatus(StrEnum):
    AVAILABLE = "available"
    NO_ROUTE = "no_route"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_ERROR = "provider_error"
    NEEDS_PRECISE_LOCATION = "needs_precise_location"


class RoutePrecision(StrEnum):
    ADDRESS = "address"
    POSTAL_CODE = "postal_code"
    DISTRICT = "district"
    CITY_TO_CITY = "city_to_city"
    RAIL_HUB = "rail_hub"
    UNKNOWN = "unknown"


class RouteConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TravelQuery(StrictModel):
    origin: str = Field(min_length=1, max_length=500)
    destination: str = Field(min_length=1, max_length=500)
    destination_search_hint: str | None = Field(default=None, min_length=1, max_length=800)
    mode: TravelMode
    departure_at: datetime | None = None


class TravelEstimate(StrictModel):
    status: CommuteStatus
    provider: str
    duration_minutes: int | None = Field(default=None, ge=1)
    distance_km: float | None = Field(default=None, ge=0)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message: str | None = Field(default=None, max_length=1_000)
    attribution: str | None = Field(default=None, max_length=500)
    attribution_url: str | None = Field(default=None, max_length=2_000)
    cache_permitted: bool = True
    cache_ttl_seconds: int | None = Field(default=None, ge=60, le=604_800)
    attempts: list[str] = Field(default_factory=list)
    precision: RoutePrecision = RoutePrecision.UNKNOWN
    confidence: RouteConfidence = RouteConfidence.LOW
    duration_low_minutes: int | None = Field(default=None, ge=1)
    duration_high_minutes: int | None = Field(default=None, ge=1)
    sample_minutes: list[int] = Field(default_factory=list, max_length=7)
    origin_resolved: str | None = Field(default=None, max_length=500)
    destination_resolved: str | None = Field(default=None, max_length=500)
    origin_precision: RoutePrecision = RoutePrecision.UNKNOWN
    destination_precision: RoutePrecision = RoutePrecision.UNKNOWN
    route_scope: str = Field(default="unknown", max_length=100)


class CommuteAssessment(StrictModel):
    profile_fact_id: UUID
    profile_key: str
    profile_value: str
    level: RequirementLevel
    origin: str
    destination: str
    mode: TravelMode
    maximum_minutes: int = Field(ge=1, le=360)
    estimate: TravelEstimate
    cached: bool = False
    evaluated_destinations: list[str] = Field(default_factory=list, max_length=12)
    unresolved_destinations: list[str] = Field(default_factory=list, max_length=12)
    omitted_destination_count: int = Field(default=0, ge=0)
    user_override_minutes: int | None = Field(default=None, ge=1, le=360)
    automatic_duration_minutes: int | None = Field(default=None, ge=1)

    @property
    def within_limit(self) -> bool | None:
        effective_minutes = self.user_override_minutes or self.estimate.duration_minutes
        if effective_minutes is None:
            return None
        if effective_minutes <= self.maximum_minutes:
            return True
        if self.unresolved_destinations or self.omitted_destination_count:
            # A failed alternative workplace could still be the reachable one.
            # Never turn that provider uncertainty into a hard candidate blocker.
            return None
        return False


class TravelTimeProvider(Protocol):
    name: str

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        """Return one route estimate without inventing missing precision."""


class OfflineRouteEndpoint(StrictModel):
    """One validated endpoint for an open-source road route."""

    label: str
    lat: float
    lon: float
    precision: RoutePrecision
    diagnostic: str


class NominatimPlaceResolver:
    """Resolve otherwise unknown European places through OpenStreetMap search.

    Local postcode and city indexes always run first. This bounded fallback is
    used only for labels such as a district or street that cannot be resolved
    locally, and its results are cached in memory.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://nominatim.openstreetmap.org",
        user_agent: str = ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        client: httpx.Client | None = None,
        timeout_seconds: float = 12.0,
        sleeper: Callable[[float], None] = time.sleep,
        minimum_request_interval_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("Nominatim base URL must use HTTP or HTTPS")
        if not user_agent.strip():
            raise ValueError("Nominatim requires an identifying User-Agent")
        self.user_agent = user_agent.strip()
        self.sleeper = sleeper
        self.minimum_request_interval_seconds = max(
            0.0,
            min(
                2.0,
                (
                    1.05
                    if minimum_request_interval_seconds is None and client is None
                    else minimum_request_interval_seconds or 0.0
                ),
            ),
        )
        self.monotonic = monotonic
        self._last_request_at: float | None = None
        self._request_lock = Lock()
        self._cache: dict[str, OfflineRouteEndpoint | None] = {}
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
        )
        self.client.headers.update({"Accept": "application/json", "User-Agent": self.user_agent})

    def resolve(self, label: str) -> OfflineRouteEndpoint | None:
        if not provider_permission_allowed("nominatim"):
            return None
        cache_key = " ".join(label.casefold().split())
        if cache_key in self._cache:
            return self._cache[cache_key]
        with self._request_lock:
            self._pace_request()
            try:
                response = self.client.get(
                    f"{self.base_url}/search",
                    params={
                        "q": label,
                        "format": "jsonv2",
                        "addressdetails": 1,
                        "limit": 5,
                        "accept-language": "en",
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, TypeError, ValueError):
                self._cache[cache_key] = None
                return None
        candidates = (
            [item for item in payload if isinstance(item, dict)]
            if isinstance(payload, list)
            else []
        )
        safe = [item for item in candidates if _nominatim_candidate_is_safe(label, item)]
        if not safe:
            self._cache[cache_key] = None
            return None
        selected = max(safe, key=lambda item: _nominatim_candidate_score(label, item))
        try:
            endpoint = OfflineRouteEndpoint(
                label=str(selected.get("display_name") or label)[:500],
                lat=float(selected["lat"]),
                lon=float(selected["lon"]),
                precision=_nominatim_precision(selected),
                diagnostic=(
                    f"Resolved “{label}” through the configured OpenStreetMap Nominatim "
                    f"geocoder as “{str(selected.get('display_name') or label)[:300]}”."
                ),
            )
        except (KeyError, TypeError, ValueError):
            endpoint = None
        self._cache[cache_key] = endpoint
        return endpoint

    def _pace_request(self) -> None:
        if self.minimum_request_interval_seconds <= 0:
            return
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = self.minimum_request_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.monotonic()
        self._last_request_at = now


class UnavailableTravelTimeProvider:
    name = "not-configured"
    persistent_cache_allowed = False

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        return TravelEstimate(
            status=CommuteStatus.PROVIDER_UNAVAILABLE,
            provider=self.name,
            message="No travel-time provider is configured.",
            cache_permitted=False,
            attempts=["No configured provider supports this route."],
        )


class GoogleRoutesTravelTimeProvider:
    """Google Routes adapter for driving, transit, cycling, and walking."""

    name = "google-routes"
    persistent_cache_allowed = False
    peak_window_sampling = True
    endpoint = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Google Routes requires a non-empty API key")
        self.api_key = api_key.strip()
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        mode = {
            TravelMode.CAR: "DRIVE",
            TravelMode.TRANSIT: "TRANSIT",
            TravelMode.BICYCLE: "BICYCLE",
            TravelMode.WALK: "WALK",
        }[query.mode]
        body: dict[str, object] = {
            "origin": {"address": query.origin},
            # Google can resolve an employer POI when the advertisement exposes
            # only a company and city. Evidence-backed street/postcode values
            # remain the primary destination and never receive this hint.
            "destination": {"address": query.destination_search_hint or query.destination},
            "travelMode": mode,
            "computeAlternativeRoutes": True,
            "languageCode": "en",
            "units": "METRIC",
        }
        if mode == "DRIVE":
            body["routingPreference"] = "TRAFFIC_AWARE"
        if query.departure_at is not None and mode in {"DRIVE", "TRANSIT"}:
            body["departureTime"] = (
                query.departure_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            )
        checked_at = datetime.now(timezone.utc)
        try:
            response = self.client.post(
                self.endpoint,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
                },
            )
            response.raise_for_status()
            routes = response.json().get("routes", [])
            if not routes:
                return TravelEstimate(
                    status=CommuteStatus.NO_ROUTE,
                    provider=self.name,
                    checked_at=checked_at,
                    message="The provider returned no route for this mode.",
                    attribution="Google Maps",
                    attribution_url="https://www.google.com/maps",
                    cache_permitted=False,
                    attempts=["Google Routes returned no route."],
                )
            route_candidates = [
                (seconds, route)
                for route in routes
                if isinstance(route, dict)
                if (seconds := _duration_seconds(str(route.get("duration", "")))) is not None
            ]
            if not route_candidates:
                raise ValueError("route response did not contain a usable duration")
            seconds, route = min(route_candidates, key=lambda item: item[0])
            distance_meters = route.get("distanceMeters")
            return TravelEstimate(
                status=CommuteStatus.AVAILABLE,
                provider=self.name,
                duration_minutes=max(1, round(seconds / 60)),
                distance_km=(
                    round(float(distance_meters) / 1_000, 1)
                    if distance_meters is not None
                    else None
                ),
                checked_at=checked_at,
                message=(
                    "Google walking and bicycling routes are beta and may omit clear paths."
                    if query.mode in {TravelMode.BICYCLE, TravelMode.WALK}
                    else None
                ),
                attribution="Google Maps",
                attribution_url="https://www.google.com/maps",
                cache_permitted=False,
                attempts=[
                    f"Google Routes returned {len(route_candidates)} valid route option(s); "
                    "WorkLifeBalance selected the shortest."
                ],
                precision=_query_precision(query),
                confidence=(
                    RouteConfidence.HIGH
                    if _query_precision(query) == RoutePrecision.ADDRESS
                    else RouteConfidence.MEDIUM
                ),
                duration_low_minutes=max(1, round(seconds / 60)),
                duration_high_minutes=max(1, round(seconds / 60)),
                sample_minutes=[max(1, round(seconds / 60))],
                origin_resolved=query.origin,
                destination_resolved=query.destination,
                origin_precision=_label_precision(query.origin),
                destination_precision=_label_precision(query.destination),
                route_scope=_route_scope(query),
            )
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_ERROR,
                provider=self.name,
                checked_at=checked_at,
                message=f"Travel-time lookup failed: {type(exc).__name__}",
                attribution="Google Maps",
                attribution_url="https://www.google.com/maps",
                cache_permitted=False,
                attempts=[f"Google Routes failed with {type(exc).__name__}."],
            )


class OpenRouteServiceTravelTimeProvider:
    """openrouteservice fallback for driving, cycling, and walking."""

    name = "openrouteservice"
    persistent_cache_allowed = True
    base_url = "https://api.openrouteservice.org"
    supported_modes = {TravelMode.CAR, TravelMode.BICYCLE, TravelMode.WALK}

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("openrouteservice requires a non-empty API key")
        self.api_key = api_key.strip()
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        checked_at = datetime.now(timezone.utc)
        if query.mode not in self.supported_modes:
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_UNAVAILABLE,
                provider=self.name,
                checked_at=checked_at,
                message="openrouteservice does not provide public-transit routes.",
                attribution=_ors_attribution(),
                attribution_url="https://openrouteservice.org/",
                attempts=["openrouteservice does not support this travel mode."],
            )
        try:
            origin = self._geocode(query.origin)
            destination = self._geocode(query.destination)
            profile = {
                TravelMode.CAR: "driving-car",
                TravelMode.BICYCLE: "cycling-regular",
                TravelMode.WALK: "foot-walking",
            }[query.mode]
            response = self.client.post(
                f"{self.base_url}/v2/directions/{profile}",
                headers={"Authorization": self.api_key, "Content-Type": "application/json"},
                json={"coordinates": [origin, destination]},
            )
            response.raise_for_status()
            routes = response.json().get("routes", [])
            if not routes:
                return TravelEstimate(
                    status=CommuteStatus.NO_ROUTE,
                    provider=self.name,
                    checked_at=checked_at,
                    message="openrouteservice returned no route.",
                    attribution=_ors_attribution(),
                    attribution_url="https://openrouteservice.org/",
                    attempts=["openrouteservice returned no route."],
                )
            summary = routes[0].get("summary", {})
            seconds = float(summary["duration"])
            distance = float(summary["distance"])
            return TravelEstimate(
                status=CommuteStatus.AVAILABLE,
                provider=self.name,
                duration_minutes=max(1, round(seconds / 60)),
                distance_km=round(distance / 1_000, 1),
                checked_at=checked_at,
                attribution=_ors_attribution(),
                attribution_url="https://openrouteservice.org/",
                attempts=["openrouteservice returned a route."],
                precision=_query_precision(query),
                confidence=RouteConfidence.MEDIUM,
                duration_low_minutes=max(1, round(seconds / 60)),
                duration_high_minutes=max(1, round(seconds / 60)),
                sample_minutes=[max(1, round(seconds / 60))],
                origin_resolved=query.origin,
                destination_resolved=query.destination,
                origin_precision=_label_precision(query.origin),
                destination_precision=_label_precision(query.destination),
                route_scope=_route_scope(query),
            )
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_ERROR,
                provider=self.name,
                checked_at=checked_at,
                message=f"openrouteservice lookup failed: {type(exc).__name__}",
                attribution=_ors_attribution(),
                attribution_url="https://openrouteservice.org/",
                attempts=[f"openrouteservice failed with {type(exc).__name__}."],
            )

    def _geocode(self, label: str) -> list[float]:
        response = self.client.get(
            f"{self.base_url}/geocode/search",
            params={"api_key": self.api_key, "text": label, "size": 1},
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        if not features:
            raise ValueError(f"location could not be geocoded: {label}")
        coordinates = features[0]["geometry"]["coordinates"]
        return [float(coordinates[0]), float(coordinates[1])]


class ValhallaTravelTimeProvider:
    """Google-free car, bicycle, and walking fallback using open-source Valhalla."""

    name = "valhalla-osm"
    persistent_cache_allowed = True
    peak_window_sampling = False
    supported_modes = {TravelMode.CAR, TravelMode.BICYCLE, TravelMode.WALK}

    def __init__(
        self,
        *,
        base_url: str = "https://valhalla1.openstreetmap.de",
        client_id: str = "betteroption.example",
        user_agent: str = ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
        sleeper: Callable[[float], None] = time.sleep,
        minimum_request_interval_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        place_index: OfflinePlaceIndex | None = None,
        postal_code_index: OfflineGermanPostalCodeIndex | None = None,
        place_resolver: NominatimPlaceResolver | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("Valhalla base URL must use HTTP or HTTPS")
        if not client_id.strip() or not user_agent.strip():
            raise ValueError("Valhalla requires an identifying client ID and User-Agent")
        self.client_id = client_id.strip()
        self.user_agent = user_agent.strip()
        self.sleeper = sleeper
        self.minimum_request_interval_seconds = max(
            0.0,
            min(
                2.0,
                (
                    1.05
                    if minimum_request_interval_seconds is None and client is None
                    else minimum_request_interval_seconds or 0.0
                ),
            ),
        )
        self.monotonic = monotonic
        self._last_request_at: float | None = None
        self._request_lock = Lock()
        self._unavailable_until = 0.0
        self.place_index = place_index or OfflinePlaceIndex()
        self.postal_code_index = postal_code_index or OfflineGermanPostalCodeIndex()
        self.place_resolver = place_resolver
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
                "X-Client-Id": self.client_id,
            },
        )
        self.client.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
                "X-Client-Id": self.client_id,
            }
        )

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        checked_at = datetime.now(timezone.utc)
        if query.mode not in self.supported_modes:
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_UNAVAILABLE,
                provider=self.name,
                checked_at=checked_at,
                message="Valhalla does not provide WorkLifeBalance's public-transit fallback.",
                attribution=_valhalla_attribution(),
                attribution_url="https://fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen/",
                attempts=["Valhalla does not support this mode in the privacy-first chain."],
            )

        origin = self._resolve_endpoint(query.origin)
        destination = self._resolve_endpoint(query.destination)
        if origin is None or destination is None:
            missing = query.origin if origin is None else query.destination
            return TravelEstimate(
                status=CommuteStatus.NEEDS_PRECISE_LOCATION,
                provider=self.name,
                checked_at=checked_at,
                message=(
                    "The Google-free route fallback could not resolve this endpoint safely. "
                    "Add a postcode, district and city, or recognisable full address: "
                    f"{missing}."
                ),
                attribution=_valhalla_attribution(),
                attribution_url="https://fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen/",
                cache_permitted=False,
                attempts=[f"Privacy-first endpoint resolution failed for “{missing}”."],
            )

        costing = {
            TravelMode.CAR: "auto",
            TravelMode.BICYCLE: "bicycle",
            TravelMode.WALK: "pedestrian",
        }[query.mode]
        payload = {
            "locations": [
                {"lat": origin.lat, "lon": origin.lon, "type": "break"},
                {"lat": destination.lat, "lon": destination.lon, "type": "break"},
            ],
            "costing": costing,
            "units": "kilometers",
            "language": "en-US",
            "directions_options": {"units": "kilometers"},
        }
        try:
            response = self._post_route(payload)
            trip = response.get("trip", {}) if isinstance(response, dict) else {}
            summary = trip.get("summary", {}) if isinstance(trip, dict) else {}
            seconds = float(summary["time"])
            distance = float(summary["length"])
            if seconds <= 0 or distance < 0:
                raise ValueError("Valhalla returned an invalid route summary")
        except (httpx.HTTPError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_ERROR,
                provider=self.name,
                checked_at=checked_at,
                message=f"Valhalla route lookup failed: {_open_route_error_diagnostic(exc)}",
                attribution=_valhalla_attribution(),
                attribution_url="https://fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen/",
                cache_permitted=False,
                attempts=[f"Valhalla failed with {_open_route_error_diagnostic(exc)}."],
            )

        minutes = max(1, round(seconds / 60))
        precision = min(
            (origin.precision, destination.precision),
            key=_precision_rank,
        )
        return TravelEstimate(
            status=CommuteStatus.AVAILABLE,
            provider=self.name,
            duration_minutes=minutes,
            distance_km=round(distance, 1),
            checked_at=checked_at,
            message=(
                "Google-free OpenStreetMap route from the community FOSSGIS demo service. "
                "It has no live traffic guarantee and is a private-alpha fallback; contact the "
                "operator or self-host Valhalla before a paid release."
            ),
            attribution=_valhalla_attribution(),
            attribution_url="https://fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen/",
            cache_ttl_seconds=43_200,
            attempts=[
                origin.diagnostic,
                destination.diagnostic,
                f"Valhalla returned one {costing} route.",
            ],
            precision=precision,
            confidence=(
                RouteConfidence.MEDIUM
                if precision in {RoutePrecision.POSTAL_CODE, RoutePrecision.DISTRICT}
                else RouteConfidence.LOW
            ),
            duration_low_minutes=minutes,
            duration_high_minutes=minutes,
            sample_minutes=[minutes],
            origin_resolved=origin.label,
            destination_resolved=destination.label,
            origin_precision=origin.precision,
            destination_precision=destination.precision,
            route_scope="area_to_area",
        )

    def _resolve_endpoint(self, label: str) -> OfflineRouteEndpoint | None:
        if postal := self.postal_code_index.resolve(label):
            return OfflineRouteEndpoint(
                label=f"{postal.label}, {postal.country_code}",
                lat=postal.latitude,
                lon=postal.longitude,
                precision=RoutePrecision.POSTAL_CODE,
                diagnostic=(
                    f"Resolved “{label}” locally as {postal.label}, {postal.country_code} "
                    "from the bundled GeoNames postcode dataset."
                ),
            )
        if place := _resolve_city_component(self.place_index, label):
            return OfflineRouteEndpoint(
                label=f"{place.label}, {place.country_code}",
                lat=place.latitude,
                lon=place.longitude,
                precision=RoutePrecision.CITY_TO_CITY,
                diagnostic=(
                    f"Resolved “{label}” locally as {place.label}, {place.country_code} "
                    "from the bundled city index."
                ),
            )
        if self.place_resolver is not None:
            return self.place_resolver.resolve(label)
        return None

    def _post_route(self, payload: dict[str, object]) -> object:
        with self._request_lock:
            if self.monotonic() < self._unavailable_until:
                raise RuntimeError("public endpoint is in a short failure cooldown")
            response: httpx.Response | None = None
            try:
                for attempt in range(3):
                    self._pace_request()
                    try:
                        response = self.client.post(f"{self.base_url}/route", json=payload)
                    except (httpx.NetworkError, httpx.TimeoutException):
                        if attempt == 2:
                            raise
                        self.sleeper(1.0)
                        continue
                    if response.status_code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                        response.raise_for_status()
                        return response.json()
                    self.sleeper(max(1.0, _transitous_retry_delay(response, 1.0)))
            except (httpx.HTTPError, RuntimeError):
                self._unavailable_until = self.monotonic() + 30.0
                raise
        raise RuntimeError("Valhalla retry loop ended without a response")

    def _pace_request(self) -> None:
        if self.minimum_request_interval_seconds <= 0:
            return
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = self.minimum_request_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.monotonic()
        self._last_request_at = now


class TransitousPlace(StrictModel):
    """One explicit geocoding decision used for a public-transport route."""

    display_name: str
    lat: float
    lon: float
    query_used: str
    station_like: bool = False
    precision: RoutePrecision = RoutePrecision.UNKNOWN
    validation_notes: list[str] = Field(default_factory=list)


class TransitousTravelTimeProvider:
    """Keyless public-transit fallback backed by Transitous/MOTIS."""

    name = "transitous"
    persistent_cache_allowed = True
    # One MOTIS plan request already asks for seven itinerary alternatives.
    # Repeating it at three departure times overloads the community endpoint
    # during a multi-job match, so the keyless fallback intentionally performs
    # one standard-Tuesday request per job.
    peak_window_sampling = False
    supported_modes = {TravelMode.TRANSIT}

    def __init__(
        self,
        *,
        base_url: str = "https://api.transitous.org",
        user_agent: str = ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
        sleeper: Callable[[float], None] = time.sleep,
        retry_delay_seconds: float = 0.4,
        minimum_request_interval_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        place_index: OfflinePlaceIndex | None = None,
        postal_code_index: OfflineGermanPostalCodeIndex | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("Transitous base URL must use HTTP or HTTPS")
        if not user_agent.strip():
            raise ValueError("Transitous requires an identifying User-Agent")
        self.user_agent = user_agent.strip()
        self.sleeper = sleeper
        self.retry_delay_seconds = max(0.0, min(retry_delay_seconds, 2.0))
        self.minimum_request_interval_seconds = max(
            0.0,
            min(
                1.0,
                (
                    0.25
                    if minimum_request_interval_seconds is None and client is None
                    else minimum_request_interval_seconds or 0.0
                ),
            ),
        )
        self.monotonic = monotonic
        self._last_request_at: float | None = None
        self._request_lock = Lock()
        self._unavailable_until = 0.0
        self.place_index = place_index or OfflinePlaceIndex()
        self.postal_code_index = postal_code_index or OfflineGermanPostalCodeIndex()
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
        )
        self.client.headers.update({"Accept": "application/json", "User-Agent": self.user_agent})
        self._geocode_cache: dict[tuple[str, bool], TransitousPlace] = {}

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        checked_at = datetime.now(timezone.utc)
        if query.mode != TravelMode.TRANSIT:
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_UNAVAILABLE,
                provider=self.name,
                checked_at=checked_at,
                message="Transitous provides this fallback only for public transport.",
                attribution=_transitous_attribution(),
                attribution_url="https://transitous.org/",
                attempts=["Transitous does not support this travel mode in WorkLifeBalance."],
            )
        try:
            origin_is_city = _is_city_level_label(query.origin)
            destination_is_city = _is_city_level_label(query.destination)
            city_level = origin_is_city and destination_is_city
            # Never invent "<city> Bahnhof" for a city-only input. Some towns
            # have no matching rail station, and a fuzzy geocoder may return a
            # similarly named station hundreds of kilometres away. Explicit
            # station labels still resolve as stations; ordinary cities use a
            # validated city-centre benchmark.
            origin = self._geocode(
                query.origin,
                prefer_station=_label_precision(query.origin) == RoutePrecision.RAIL_HUB,
            )
            destination = self._geocode(
                query.destination,
                prefer_station=_label_precision(query.destination) == RoutePrecision.RAIL_HUB,
            )
            resolved_distance = _coordinate_distance_km(origin, destination)
            if city_level and resolved_distance < 2:
                return TravelEstimate(
                    status=CommuteStatus.NEEDS_PRECISE_LOCATION,
                    provider=self.name,
                    checked_at=checked_at,
                    message=(
                        "Origin and job location identify only the same city. Add a district, "
                        "postcode, station, or street to calculate a meaningful commute."
                    ),
                    attribution=_transitous_attribution(),
                    attribution_url="https://transitous.org/",
                    cache_ttl_seconds=43_200,
                    attempts=[
                        f"Resolved both city-level labels to the same local area ({resolved_distance:.1f} km apart)."
                    ],
                    precision=RoutePrecision.CITY_TO_CITY,
                )
            parameters: dict[str, object] = {
                "fromPlace": f"{origin.lat},{origin.lon}",
                "toPlace": f"{destination.lat},{destination.lon}",
                "transitModes": "TRANSIT",
                "directModes": "",
                "numItineraries": 7,
                "maxItineraries": 7,
                "detailedLegs": False,
                "arriveBy": False,
            }
            if query.departure_at is not None:
                parameters["time"] = query.departure_at.astimezone(timezone.utc).isoformat()
            itineraries = self._plan(parameters)
            recovery_attempt: str | None = None
            if not itineraries and (origin_is_city or destination_is_city):
                alternative_origin = (
                    self._geocode(query.origin, prefer_station=False) if origin_is_city else origin
                )
                alternative_destination = (
                    self._geocode(query.destination, prefer_station=False)
                    if destination_is_city
                    else destination
                )
                if _route_endpoints_differ(
                    origin,
                    destination,
                    alternative_origin,
                    alternative_destination,
                ):
                    parameters.update(
                        {
                            "fromPlace": f"{alternative_origin.lat},{alternative_origin.lon}",
                            "toPlace": (
                                f"{alternative_destination.lat},{alternative_destination.lon}"
                            ),
                        }
                    )
                    itineraries = self._plan(parameters)
                    recovery_attempt = (
                        "The station benchmark returned no itinerary, so Transitous was retried "
                        "once with the resolved city centres."
                    )
                    if itineraries:
                        origin = alternative_origin
                        destination = alternative_destination
            if not itineraries:
                attempts = [
                    f"Transitous resolved origin via “{origin.query_used}” as “{origin.display_name}”.",
                    (
                        "Transitous resolved destination via "
                        f"“{destination.query_used}” as “{destination.display_name}”."
                    ),
                ]
                if recovery_attempt:
                    attempts.append(recovery_attempt)
                attempts.append("Transitous/MOTIS returned no itinerary.")
                return TravelEstimate(
                    status=CommuteStatus.NO_ROUTE,
                    provider=self.name,
                    checked_at=checked_at,
                    message="Transitous returned no public-transport itinerary.",
                    attribution=_transitous_attribution(),
                    attribution_url="https://transitous.org/",
                    cache_ttl_seconds=43_200,
                    attempts=attempts,
                )
            duration_candidates = [
                (seconds, discrepancy)
                for itinerary in itineraries
                if isinstance(itinerary, dict)
                if (parsed := _transitous_itinerary_duration(itinerary)) is not None
                for seconds, discrepancy in [parsed]
            ]
            if not duration_candidates:
                raise ValueError("Transitous returned itineraries without valid durations")
            seconds, discrepancy = min(duration_candidates, key=lambda item: item[0])
            attempts = [
                (
                    "Standard comparison departure: "
                    f"{query.departure_at.astimezone(ZoneInfo('Europe/Berlin')).strftime('%A, %d %b %Y at %H:%M %Z')}."
                    if query.departure_at is not None
                    else "No fixed departure time was requested."
                ),
                (
                    f"Transitous resolved “{query.origin}” as “{origin.display_name}” "
                    f"({origin.lat:.5f}, {origin.lon:.5f}) via “{origin.query_used}”."
                ),
                (
                    f"Transitous resolved “{query.destination}” as "
                    f"“{destination.display_name}” ({destination.lat:.5f}, "
                    f"{destination.lon:.5f}) via “{destination.query_used}”."
                ),
                f"MOTIS returned {len(duration_candidates)} valid itinerary option(s).",
            ]
            attempts.extend(origin.validation_notes)
            attempts.extend(destination.validation_notes)
            if recovery_attempt:
                attempts.append(recovery_attempt)
            if city_level:
                attempts.append(
                    "City-only inputs were routed as a validated city-centre benchmark; "
                    "this is not door-to-door time."
                )
            if discrepancy:
                attempts.append(discrepancy)
            return TravelEstimate(
                status=CommuteStatus.AVAILABLE,
                provider=self.name,
                duration_minutes=max(1, round(seconds / 60)),
                checked_at=checked_at,
                message=(
                    "Community-run, best-effort public-transit estimate. Verify the journey "
                    "with the local operator before relying on it. Public endpoint use is "
                    "private-alpha only; obtain approval or self-host before a paid release."
                ),
                attribution=_transitous_attribution(),
                attribution_url="https://transitous.org/",
                cache_ttl_seconds=43_200,
                attempts=attempts,
                precision=_transitous_route_precision(
                    query,
                    origin=origin,
                    destination=destination,
                ),
                confidence=RouteConfidence.MEDIUM if city_level else RouteConfidence.LOW,
                duration_low_minutes=max(1, round(seconds / 60)),
                duration_high_minutes=max(1, round(seconds / 60)),
                sample_minutes=[max(1, round(seconds / 60))],
                origin_resolved=origin.display_name,
                destination_resolved=destination.display_name,
                origin_precision=(
                    _transitous_endpoint_precision(origin)
                    if origin_is_city
                    else _label_precision(query.origin)
                ),
                destination_precision=(
                    _transitous_endpoint_precision(destination)
                    if destination_is_city
                    else _label_precision(query.destination)
                ),
                route_scope=_transitous_route_scope(
                    query,
                    origin=origin,
                    destination=destination,
                ),
            )
        except (httpx.HTTPError, KeyError, IndexError, RuntimeError, TypeError, ValueError) as exc:
            diagnostic = _transitous_error_diagnostic(exc)
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_ERROR,
                provider=self.name,
                checked_at=checked_at,
                message=f"Transitous lookup failed: {diagnostic}",
                attribution=_transitous_attribution(),
                attribution_url="https://transitous.org/",
                cache_permitted=False,
                attempts=[f"Transitous/MOTIS failed with {diagnostic}."],
            )

    def _geocode(self, label: str, *, prefer_station: bool = False) -> TransitousPlace:
        cache_key = (" ".join(label.casefold().split()), prefer_station)
        if cached := self._geocode_cache.get(cache_key):
            return cached

        # The MOTIS geocoder treats a bare German postcode as fuzzy text and
        # can truncate it (60486 became unrelated 6048 results). Resolve the
        # complete postcode locally instead and send only coordinates to the
        # route planner. Street addresses remain provider-resolved.
        if _label_precision(label) == RoutePrecision.POSTAL_CODE:
            postal_place = self.postal_code_index.resolve(label)
            if postal_place is not None:
                place = TransitousPlace(
                    display_name=f"{postal_place.label}, {postal_place.country_code}",
                    lat=postal_place.latitude,
                    lon=postal_place.longitude,
                    query_used=f"local GeoNames postcode {postal_place.postal_code}",
                    precision=RoutePrecision.POSTAL_CODE,
                    validation_notes=[
                        "The German postcode was resolved locally from the bundled GeoNames "
                        "postal-code dataset; no postcode geocoding request was sent."
                    ],
                )
                self._geocode_cache[cache_key] = place
                return place

        failures: list[str] = []
        rejection_notes: list[str] = []
        for query_text in _transitous_geocode_queries(label, prefer_station=prefer_station):
            matches = self._get_json(
                "/api/v1/geocode",
                params={"text": query_text, "language": "en", "numResults": 8},
            )
            candidates = (
                [
                    match
                    for match in matches
                    if isinstance(match, dict)
                    and match.get("lat") is not None
                    and match.get("lon") is not None
                ]
                if isinstance(matches, list)
                else []
            )
            if not candidates:
                failures.append(query_text)
                continue
            for selected in sorted(
                candidates,
                key=lambda match: _transitous_place_score(query_text, match),
                reverse=True,
            ):
                place = TransitousPlace(
                    display_name=_transitous_place_name(selected, label),
                    lat=float(selected["lat"]),
                    lon=float(selected["lon"]),
                    query_used=query_text,
                    station_like=_transitous_station_like(selected),
                )
                issue = _transitous_place_issue(
                    label,
                    place,
                    selected,
                    place_index=self.place_index,
                )
                if issue:
                    rejection_notes.append(
                        f"Rejected geocoder candidate “{place.display_name}”: {issue}"
                    )
                    continue
                place = place.model_copy(
                    update={
                        "precision": (
                            RoutePrecision.RAIL_HUB
                            if place.station_like
                            else RoutePrecision.CITY_TO_CITY
                        ),
                        "validation_notes": rejection_notes[-3:],
                    }
                )
                self._geocode_cache[cache_key] = place
                return place
            failures.append(query_text)
        attempted = ", ".join(f"“{query}”" for query in failures)
        detail = f"; {' '.join(rejection_notes[-3:])}" if rejection_notes else ""
        raise ValueError(
            f"location could not be geocoded safely: {label}; attempted {attempted}{detail}"
        )

    def _plan(self, parameters: dict[str, object]) -> list[dict[str, object]]:
        payload = self._get_json("/api/v6/plan", params=parameters)
        itineraries = payload.get("itineraries", []) if isinstance(payload, dict) else []
        return [item for item in itineraries if isinstance(item, dict)]

    def _get_json(self, path: str, *, params: dict[str, object]) -> object:
        """Retry one explicitly temporary public-endpoint response."""

        with self._request_lock:
            if self.monotonic() < self._unavailable_until:
                raise RuntimeError("public endpoint is in a short failure cooldown")
            response: httpx.Response | None = None
            temporary_statuses = {408, 429, 500, 502, 503, 504}
            try:
                for attempt in range(3):
                    self._pace_request()
                    try:
                        response = self.client.get(f"{self.base_url}{path}", params=params)
                    except (httpx.NetworkError, httpx.TimeoutException):
                        if attempt == 2:
                            raise
                        self.sleeper(min(2.0, self.retry_delay_seconds * (2**attempt)))
                        continue
                    if response.status_code not in temporary_statuses or attempt == 2:
                        response.raise_for_status()
                        return response.json()
                    self.sleeper(
                        _transitous_retry_delay(
                            response,
                            min(2.0, self.retry_delay_seconds * (2**attempt)),
                        )
                    )
            except (httpx.HTTPError, RuntimeError):
                self._unavailable_until = self.monotonic() + 30.0
                raise
        raise RuntimeError("Transitous retry loop ended without a response")

    def _pace_request(self) -> None:
        if self.minimum_request_interval_seconds <= 0:
            return
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = self.minimum_request_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.monotonic()
        self._last_request_at = now


def _transitous_geocode_query(label: str, *, prefer_station: bool = False) -> str:
    """Disambiguate the common Frankfurt shorthand without guessing other cities."""

    clean = " ".join(label.split())
    normalized = clean.casefold().replace(".", "")
    if normalized in {"frankfurt", "frankfurt am main", "frankfurt/main"}:
        return (
            "Frankfurt (Main) Hauptbahnhof, Germany"
            if prefer_station
            else "Frankfurt am Main, Hessen, Germany"
        )
    if prefer_station and not any(
        marker in normalized for marker in ("bahnhof", "hauptbahnhof", " hbf", "station")
    ):
        return f"{clean} Bahnhof"
    return clean


def _transitous_retry_delay(response: httpx.Response, default: float) -> float:
    retry_after = response.headers.get("Retry-After", "").strip()
    try:
        return max(0.0, min(float(retry_after), 2.0)) if retry_after else default
    except ValueError:
        return default


def _transitous_error_diagnostic(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, ValueError) and str(exc):
        return f"ValueError: {str(exc)[:700]}"
    return type(exc).__name__


def _transitous_geocode_queries(label: str, *, prefer_station: bool = False) -> tuple[str, ...]:
    """Return bounded geocoder fallbacks without multiplying successful API calls."""

    plain = _transitous_geocode_query(label, prefer_station=False)
    primary = _transitous_geocode_query(label, prefer_station=prefer_station)
    candidates = [primary]
    if not prefer_station and not _label_has_country(plain):
        candidates = [f"{plain}, Germany", plain]
    if prefer_station:
        if not _label_has_country(plain):
            candidates.append(f"{plain}, Germany")
        candidates.append(plain)
    return tuple(dict.fromkeys(candidates))


_PLACE_IDENTITY_STOPWORDS = {
    "am",
    "an",
    "bahnhof",
    "de",
    "deutschland",
    "germany",
    "hauptbahnhof",
    "hbf",
    "in",
    "main",
    "station",
}


def _transitous_place_issue(
    requested_label: str,
    place: TransitousPlace,
    match: dict[str, object],
    *,
    place_index: OfflinePlaceIndex,
) -> str | None:
    """Reject fuzzy results that do not identify the requested locality."""

    requested_tokens = {
        token
        for token in re.findall(r"[a-z0-9äöüß]+", requested_label.casefold())
        if len(token) >= 3 and token not in _PLACE_IDENTITY_STOPWORDS
    }
    areas = [
        str(area.get("name") or "") for area in (match.get("areas") or []) if isinstance(area, dict)
    ]
    candidate_material = " ".join(
        (str(match.get("name") or ""), str(match.get("country") or ""), *areas)
    ).casefold()
    candidate_tokens = set(re.findall(r"[a-z0-9äöüß]+", candidate_material))
    if requested_tokens and not requested_tokens.intersection(candidate_tokens):
        return "the requested locality does not occur in the result name or administrative areas"

    expected = _resolve_city_component(place_index, requested_label)
    if expected is not None:
        resolved = ResolvedPlace(
            label=place.display_name,
            country_code=str(match.get("country") or expected.country_code),
            latitude=place.lat,
            longitude=place.lon,
        )
        distance = straight_line_distance_km(expected, resolved)
        if distance > 25:
            return f"the result is {distance:.0f} km from the expected {expected.label} locality"
    return None


def _label_has_country(label: str) -> bool:
    normalized = label.casefold()
    return any(
        marker in normalized
        for marker in ("germany", "deutschland", "austria", "österreich", "switzerland", "schweiz")
    )


def _transitous_station_like(match: dict[str, object]) -> bool:
    material = " ".join(
        str(value or "")
        for value in (
            match.get("name"),
            match.get("type"),
            match.get("vertexType"),
        )
    ).casefold()
    return any(
        marker in material for marker in ("bahnhof", "hauptbahnhof", " hbf", "station", "stop")
    )


def _transitous_endpoint_precision(place: TransitousPlace) -> RoutePrecision:
    if place.precision != RoutePrecision.UNKNOWN:
        return place.precision
    return RoutePrecision.RAIL_HUB if place.station_like else RoutePrecision.CITY_TO_CITY


def _transitous_route_precision(
    query: TravelQuery,
    *,
    origin: TransitousPlace,
    destination: TransitousPlace,
) -> RoutePrecision:
    if _city_level_pair(query):
        return (
            RoutePrecision.RAIL_HUB
            if origin.station_like and destination.station_like
            else RoutePrecision.CITY_TO_CITY
        )
    return _query_precision(query)


def _transitous_route_scope(
    query: TravelQuery,
    *,
    origin: TransitousPlace,
    destination: TransitousPlace,
) -> str:
    if query.mode != TravelMode.TRANSIT:
        return _route_scope(query)
    origin_scope = "station" if origin.station_like else "area"
    destination_scope = "station" if destination.station_like else "area"
    return f"{origin_scope}_to_{destination_scope}"


def _route_endpoints_differ(
    origin: TransitousPlace,
    destination: TransitousPlace,
    alternative_origin: TransitousPlace,
    alternative_destination: TransitousPlace,
) -> bool:
    return any(
        abs(left - right) > 0.0001
        for left, right in (
            (origin.lat, alternative_origin.lat),
            (origin.lon, alternative_origin.lon),
            (destination.lat, alternative_destination.lat),
            (destination.lon, alternative_destination.lon),
        )
    )


def _transitous_place_score(query_text: str, match: dict[str, object]) -> float:
    query_tokens = set(re.findall(r"[\w]+", query_text.casefold(), flags=re.UNICODE))
    name = str(match.get("name") or "")
    country = str(match.get("country") or "")
    area_names = [
        str(area.get("name") or "") for area in (match.get("areas") or []) if isinstance(area, dict)
    ]
    material = " ".join((name, country, *area_names)).casefold()
    material_tokens = set(re.findall(r"[\w]+", material, flags=re.UNICODE))
    token_hits = len(query_tokens.intersection(material_tokens))
    internal_score = float(match.get("score") or 0)
    importance = float(match.get("importance") or 0)
    matched_areas = sum(
        bool(area.get("matched")) for area in (match.get("areas") or []) if isinstance(area, dict)
    )
    score = token_hits * 20 + matched_areas * 5 + internal_score + importance
    normalized_query = query_text.casefold()
    if "frankfurt" in normalized_query and "main" in normalized_query:
        if "frankfurt am main" in material or (
            "frankfurt" in name.casefold() and "main" in material
        ):
            score += 200
        if "oder" in material:
            score -= 200
    station_query = any(marker in normalized_query for marker in ("bahnhof", "hauptbahnhof"))
    station_material = any(marker in material for marker in ("bahnhof", "hauptbahnhof", " hbf"))
    match_type = str(match.get("type") or match.get("vertexType") or "").casefold()
    if station_query and (station_material or match_type in {"stop", "station"}):
        score += 120
    return score


def _transitous_place_name(match: dict[str, object], fallback: str) -> str:
    name = str(match.get("name") or fallback).strip()
    areas = [
        str(area.get("name") or "").strip()
        for area in (match.get("areas") or [])
        if isinstance(area, dict) and str(area.get("name") or "").strip()
    ]
    distinguishing_area = next(
        (area for area in areas if area.casefold() not in name.casefold()), ""
    )
    country = str(match.get("country") or "").strip()
    parts = [name]
    if distinguishing_area:
        parts.append(distinguishing_area)
    if country and country.casefold() not in " ".join(parts).casefold():
        parts.append(country.upper() if len(country) == 2 else country)
    return ", ".join(parts)


def _transitous_itinerary_duration(
    itinerary: dict[str, object],
) -> tuple[float, str | None] | None:
    try:
        declared = float(itinerary["duration"])
    except (KeyError, TypeError, ValueError):
        return None
    if declared <= 0:
        return None

    start = _parse_transitous_datetime(itinerary.get("startTime"))
    end = _parse_transitous_datetime(itinerary.get("endTime"))
    if start is None or end is None or end <= start:
        return declared, None
    elapsed = (end - start).total_seconds()
    if abs(elapsed - declared) <= 60:
        return declared, None
    return elapsed, (
        "MOTIS duration disagreed with its timestamps; WorkLifeBalance used the "
        f"timestamp interval ({round(elapsed / 60)} min) instead of "
        f"{round(declared / 60)} min."
    )


def _parse_transitous_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class FallbackTravelTimeProvider:
    """Try configured providers in order and preserve every diagnostic."""

    name = "fallback-chain"

    def __init__(self, providers: list[TravelTimeProvider]) -> None:
        if not providers:
            raise ValueError("fallback provider requires at least one provider")
        self.providers = providers
        self.persistent_cache_allowed = any(
            getattr(provider, "persistent_cache_allowed", True) for provider in providers
        )
        # A cached fallback must never bypass a higher-priority provider that
        # deliberately forbids persistent route caching (Google Routes). The
        # chain may still save an open-data fallback result for privacy-first
        # runs, but balanced runs must try their configured preferred provider.
        self.persistent_cache_read_allowed = getattr(providers[0], "persistent_cache_allowed", True)
        self.peak_window_sampling = any(
            getattr(provider, "peak_window_sampling", False) for provider in providers
        )

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        attempts: list[str] = []
        last: TravelEstimate | None = None
        for provider in self.providers:
            supported = getattr(provider, "supported_modes", None)
            if supported is not None and query.mode not in supported:
                attempts.append(f"{provider.name} does not support {query.mode.value}.")
                continue
            estimate = provider.estimate(query)
            attempts.extend(estimate.attempts or [f"{provider.name}: {estimate.status.value}"])
            last = estimate
            if estimate.status == CommuteStatus.AVAILABLE:
                return estimate.model_copy(update={"attempts": attempts})
        if last is None:
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_UNAVAILABLE,
                provider=self.name,
                message=f"No configured provider supports {query.mode.value}.",
                cache_permitted=False,
                attempts=attempts,
            )
        return last.model_copy(update={"attempts": attempts})


class CommuteEstimateRow(Base):
    __tablename__ = "commute_estimates"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "job_record_id",
            "query_fingerprint",
            name="uq_commute_estimate_query",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(500), nullable=False)
    destination: Mapped[str] = mapped_column(String(500), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    departure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_low_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_high_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_minutes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    origin_resolved: Mapped[str | None] = mapped_column(String(500), nullable=True)
    destination_resolved: Mapped[str | None] = mapped_column(String(500), nullable=True)
    origin_precision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    destination_precision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    route_scope: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommuteRepository:
    def __init__(self, database: Database) -> None:
        self.session_factory = database.session_factory

    def get(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        query: TravelQuery,
        *,
        now: datetime | None = None,
    ) -> TravelEstimate | None:
        now = now or datetime.now(timezone.utc)
        fingerprint = query_fingerprint(query)
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(CommuteEstimateRow).where(
                    CommuteEstimateRow.workspace_id == str(workspace_id),
                    CommuteEstimateRow.job_record_id == str(job_record_id),
                    CommuteEstimateRow.query_fingerprint == fingerprint,
                )
            )
            if row is None or _as_utc(row.expires_at) <= now:
                return None
            return TravelEstimate(
                status=CommuteStatus(row.status),
                provider=row.provider,
                duration_minutes=row.duration_minutes,
                duration_low_minutes=row.duration_low_minutes or row.duration_minutes,
                duration_high_minutes=row.duration_high_minutes or row.duration_minutes,
                sample_minutes=_stored_samples(row.sample_minutes_json, row.duration_minutes),
                distance_km=row.distance_km,
                checked_at=_as_utc(row.checked_at),
                message=row.message,
                attribution=_provider_attribution(row.provider)[0],
                attribution_url=_provider_attribution(row.provider)[1],
                attempts=[f"Loaded a permitted cached result from {row.provider}."],
                precision=_stored_precision(row.precision, query, row.provider),
                confidence=_stored_confidence(row.confidence),
                origin_resolved=row.origin_resolved or query.origin,
                destination_resolved=row.destination_resolved or query.destination,
                origin_precision=_stored_endpoint_precision(
                    row.origin_precision, query.origin, row.provider
                ),
                destination_precision=_stored_endpoint_precision(
                    row.destination_precision, query.destination, row.provider
                ),
                route_scope=row.route_scope or _route_scope(query),
            )

    def save(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        query: TravelQuery,
        estimate: TravelEstimate,
        *,
        ttl: timedelta,
    ) -> None:
        fingerprint = query_fingerprint(query)
        with self.session_factory.begin() as database_session:
            row = database_session.scalar(
                select(CommuteEstimateRow).where(
                    CommuteEstimateRow.workspace_id == str(workspace_id),
                    CommuteEstimateRow.job_record_id == str(job_record_id),
                    CommuteEstimateRow.query_fingerprint == fingerprint,
                )
            )
            values = {
                "origin": query.origin,
                "destination": query.destination,
                "mode": query.mode.value,
                "departure_at": query.departure_at,
                "status": estimate.status.value,
                "provider": estimate.provider,
                "duration_minutes": estimate.duration_minutes,
                "duration_low_minutes": estimate.duration_low_minutes,
                "duration_high_minutes": estimate.duration_high_minutes,
                "sample_minutes_json": json.dumps(estimate.sample_minutes),
                "distance_km": estimate.distance_km,
                "precision": estimate.precision.value,
                "confidence": estimate.confidence.value,
                "origin_resolved": estimate.origin_resolved,
                "destination_resolved": estimate.destination_resolved,
                "origin_precision": estimate.origin_precision.value,
                "destination_precision": estimate.destination_precision.value,
                "route_scope": estimate.route_scope,
                "message": estimate.message,
                "checked_at": estimate.checked_at,
                "expires_at": estimate.checked_at + ttl,
            }
            if row is None:
                row = CommuteEstimateRow(
                    id=str(uuid4()),
                    workspace_id=str(workspace_id),
                    job_record_id=str(job_record_id),
                    query_fingerprint=fingerprint,
                    **values,
                )
                database_session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)


class MobilityService:
    def __init__(
        self,
        repository: CommuteRepository,
        provider: TravelTimeProvider,
        *,
        cache_ttl: timedelta = timedelta(days=7),
        place_index: OfflinePlaceIndex | None = None,
        operation_ledger: ProviderOperationLedger | None = None,
        operation_budget: ProviderBudgetPolicy | None = None,
        estimated_costs: dict[str, float] | None = None,
        enforce_provider_permissions: bool = True,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.cache_ttl = cache_ttl
        self.place_index = place_index or OfflinePlaceIndex()
        self.operation_ledger = operation_ledger
        self.operation_budget = operation_budget
        self.estimated_costs = estimated_costs or {}
        self.enforce_provider_permissions = enforce_provider_permissions

    def assess(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        profile: CandidateProfile,
        destination: str | Sequence[str],
        *,
        company: str | None = None,
    ) -> list[CommuteAssessment]:
        request = mobility_request_from_profile(profile)
        destinations, omitted_destination_count = _normalized_routing_destinations(destination)
        if request is None or not destinations:
            return []
        origin, constraints = request
        assessments: list[CommuteAssessment] = []
        for fact, mode, maximum_minutes in constraints:
            candidates = [
                self._assess_destination(
                    workspace_id,
                    job_record_id,
                    fact,
                    origin,
                    destination_label,
                    mode,
                    maximum_minutes,
                    company=company,
                )
                for destination_label in destinations
            ]
            assessments.append(
                _select_destination_assessment(
                    candidates,
                    destinations,
                    omitted_destination_count=omitted_destination_count,
                )
            )
        return assessments

    def _assess_destination(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        fact: ProfileFact,
        origin: str,
        destination: str,
        mode: TravelMode,
        maximum_minutes: int,
        *,
        company: str | None,
    ) -> CommuteAssessment:
        query = TravelQuery(
            origin=origin,
            destination=destination,
            destination_search_hint=_company_destination_search_hint(company, destination),
            mode=mode,
            departure_at=(
                _next_peak_departure() if mode in {TravelMode.CAR, TravelMode.TRANSIT} else None
            ),
        )
        precision_estimate = _same_city_precision_estimate(
            query,
            place_index=self.place_index,
        )
        allow_cache = getattr(
            self.provider,
            "persistent_cache_read_allowed",
            getattr(self.provider, "persistent_cache_allowed", True),
        )
        estimate = self.repository.get(workspace_id, job_record_id, query) if allow_cache else None
        if (
            estimate is not None
            and self.enforce_provider_permissions
            and not all(provider_permission_allowed(name) for name in estimate.provider.split("+"))
        ):
            estimate = None
        cached = estimate is not None
        if estimate is None:
            estimate = precision_estimate or self._estimate(query)
            if estimate.cache_permitted and estimate.status in {
                CommuteStatus.AVAILABLE,
                CommuteStatus.NO_ROUTE,
            }:
                self.repository.save(
                    workspace_id,
                    job_record_id,
                    query,
                    estimate,
                    ttl=(
                        timedelta(seconds=estimate.cache_ttl_seconds)
                        if estimate.cache_ttl_seconds is not None
                        else self.cache_ttl
                    ),
                )
        return CommuteAssessment(
            profile_fact_id=fact.id,
            profile_key=fact.key,
            profile_value=str(fact.value),
            level=fact.level,
            origin=origin,
            destination=destination,
            mode=mode,
            maximum_minutes=maximum_minutes,
            estimate=estimate,
            cached=cached,
        )

    def _estimate(self, query: TravelQuery) -> TravelEstimate:
        if not (
            query.departure_at is not None
            and query.mode in {TravelMode.CAR, TravelMode.TRANSIT}
            and getattr(self.provider, "peak_window_sampling", False)
        ):
            return self._single_estimate(query)

        estimates: list[TravelEstimate] = []
        all_attempts: list[str] = []
        for departure in _peak_departure_window(query.departure_at):
            sample_query = query.model_copy(update={"departure_at": departure})
            estimate = self._single_estimate(sample_query)
            estimates.append(estimate)
            local_time = departure.astimezone(ZoneInfo("Europe/Berlin")).strftime("%H:%M")
            result = (
                f"{estimate.duration_minutes} min"
                if estimate.duration_minutes is not None
                else estimate.status.value.replace("_", " ")
            )
            all_attempts.append(f"{local_time} sample via {estimate.provider}: {result}.")
            all_attempts.extend(estimate.attempts)

        available = [
            estimate
            for estimate in estimates
            if estimate.status == CommuteStatus.AVAILABLE and estimate.duration_minutes is not None
        ]
        if not available:
            last = estimates[-1]
            return last.model_copy(update={"attempts": all_attempts})

        durations = sorted(estimate.duration_minutes for estimate in available)
        median_minutes = max(1, round(median(durations)))
        representative = min(
            available,
            key=lambda estimate: abs((estimate.duration_minutes or 0) - median_minutes),
        )
        distances = [
            estimate.distance_km for estimate in available if estimate.distance_km is not None
        ]
        providers = list(dict.fromkeys(estimate.provider for estimate in available))
        confidence = _aggregate_confidence(representative, len(available))
        return representative.model_copy(
            update={
                "provider": "+".join(providers),
                "duration_minutes": median_minutes,
                "duration_low_minutes": min(durations),
                "duration_high_minutes": max(durations),
                "sample_minutes": durations,
                "distance_km": round(median(distances), 1) if distances else None,
                "checked_at": max(estimate.checked_at for estimate in available),
                "message": _window_message(representative.message, len(available)),
                "cache_permitted": all(estimate.cache_permitted for estimate in available),
                "cache_ttl_seconds": _minimum_cache_ttl(available),
                "attempts": all_attempts,
                "confidence": confidence,
            }
        )

    def _single_estimate(self, query: TravelQuery) -> TravelEstimate:
        if isinstance(self.provider, FallbackTravelTimeProvider):
            attempts: list[str] = []
            last: TravelEstimate | None = None
            for provider in self.provider.providers:
                supported = getattr(provider, "supported_modes", None)
                if supported is not None and query.mode not in supported:
                    attempts.append(f"{provider.name} does not support {query.mode.value}.")
                    continue
                estimate = _complete_route_metadata(self._provider_estimate(provider, query), query)
                issue = _plausibility_issue(query, estimate, self.place_index)
                if issue:
                    attempts.extend(estimate.attempts)
                    attempts.append(f"{provider.name} result rejected: {issue}")
                    last = _rejected_estimate(estimate, issue)
                    continue
                attempts.extend(estimate.attempts)
                last = estimate
                if estimate.status == CommuteStatus.AVAILABLE:
                    return estimate.model_copy(update={"attempts": attempts})
            if last is not None:
                return last.model_copy(update={"attempts": attempts})
            return TravelEstimate(
                status=CommuteStatus.PROVIDER_UNAVAILABLE,
                provider=self.provider.name,
                message=f"No configured provider supports {query.mode.value}.",
                cache_permitted=False,
                attempts=attempts,
            )

        estimate = _complete_route_metadata(self._provider_estimate(self.provider, query), query)
        issue = _plausibility_issue(query, estimate, self.place_index)
        return _rejected_estimate(estimate, issue) if issue else estimate

    def _provider_estimate(
        self,
        provider: TravelTimeProvider,
        query: TravelQuery,
    ) -> TravelEstimate:
        """Call one route provider and account for it without retaining locations."""

        estimated_cost = self.estimated_costs.get(provider.name) or None
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        if self.enforce_provider_permissions and not provider_permission_allowed(provider.name):
            estimate = TravelEstimate(
                status=CommuteStatus.PROVIDER_UNAVAILABLE,
                provider=provider.name,
                message=f"{provider.name} is disabled under Account → provider choices.",
                cache_permitted=False,
            )
            self._record_provider_operation(
                provider.name,
                query.mode,
                started_at,
                started,
                ProviderOperationOutcome.BLOCKED,
                estimate,
                budget_decision=BudgetDecision.BLOCKED,
                estimated_cost_usd=None,
                error_type="AccountProviderDisabled",
            )
            return estimate
        reservation = (
            self.operation_budget.reserve(
                operation_id=uuid4(),
                provider=provider.name,
                purpose=f"routing:{query.mode.value}",
                started_at=started_at,
                unit_count=1,
                unit_name="operation",
                estimated_cost_usd=estimated_cost,
            )
            if self.operation_budget is not None
            else None
        )
        if self.operation_budget is not None and reservation is None:
            estimate = TravelEstimate(
                status=CommuteStatus.PROVIDER_UNAVAILABLE,
                provider=provider.name,
                message="The private-alpha provider budget has been reached.",
                cache_permitted=False,
            )
            return estimate
        try:
            estimate = provider.estimate(query)
        except BaseException as exc:
            if reservation is not None and self.operation_ledger is not None:
                self.operation_ledger.finalize_reservation(
                    reservation,
                    outcome=ProviderOperationOutcome.FAILED,
                    finished_at=datetime.now(timezone.utc),
                    latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
                    usage_known=False,
                    error_type=type(exc).__name__,
                )
            else:
                self._record_provider_operation(
                    provider.name,
                    query.mode,
                    started_at,
                    started,
                    ProviderOperationOutcome.FAILED,
                    None,
                    estimated_cost_usd=estimated_cost,
                    error_type=type(exc).__name__,
                )
            raise
        outcome = (
            ProviderOperationOutcome.FAILED
            if estimate.status in {CommuteStatus.PROVIDER_ERROR, CommuteStatus.PROVIDER_UNAVAILABLE}
            else ProviderOperationOutcome.SUCCEEDED
        )
        if reservation is not None and self.operation_ledger is not None:
            self.operation_ledger.finalize_reservation(
                reservation,
                outcome=outcome,
                finished_at=datetime.now(timezone.utc),
                latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
                result_count=(1 if estimate.status == CommuteStatus.AVAILABLE else 0),
                actual_unit_count=1,
                actual_cost_usd=estimated_cost,
                usage_known=True,
            )
        else:
            self._record_provider_operation(
                provider.name,
                query.mode,
                started_at,
                started,
                outcome,
                estimate,
                estimated_cost_usd=estimated_cost,
            )
        return estimate

    def _record_provider_operation(
        self,
        provider: str,
        mode: TravelMode,
        started_at: datetime,
        started: float,
        outcome: ProviderOperationOutcome,
        estimate: TravelEstimate | None,
        *,
        budget_decision: BudgetDecision = BudgetDecision.ALLOWED,
        estimated_cost_usd: float | None = None,
        error_type: str | None = None,
    ) -> None:
        if self.operation_ledger is None:
            return
        self.operation_ledger.record(
            ProviderOperation(
                provider=provider,
                purpose=f"routing:{mode.value}",
                outcome=outcome,
                budget_decision=budget_decision,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
                result_count=(
                    1 if estimate is not None and estimate.status == CommuteStatus.AVAILABLE else 0
                ),
                estimated_cost_usd=estimated_cost_usd,
                error_type=error_type,
            )
        )


def _peak_departure_window(departure: datetime) -> tuple[datetime, datetime, datetime]:
    return (
        departure - timedelta(minutes=30),
        departure,
        departure + timedelta(minutes=30),
    )


def _aggregate_confidence(
    representative: TravelEstimate,
    sample_count: int,
) -> RouteConfidence:
    if sample_count < 2:
        return RouteConfidence.LOW
    if sample_count >= 3 and representative.confidence == RouteConfidence.HIGH:
        return RouteConfidence.HIGH
    return RouteConfidence.MEDIUM


def _window_message(existing: str | None, sample_count: int) -> str:
    statement = (
        f"Typical weekday estimate from {sample_count} morning departure samples; "
        "the median is used for matching and the full range remains visible."
    )
    return f"{statement} {existing}" if existing else statement


def _minimum_cache_ttl(estimates: list[TravelEstimate]) -> int | None:
    values = [
        estimate.cache_ttl_seconds
        for estimate in estimates
        if estimate.cache_ttl_seconds is not None
    ]
    return min(values) if values else None


def _complete_route_metadata(estimate: TravelEstimate, query: TravelQuery) -> TravelEstimate:
    if estimate.status != CommuteStatus.AVAILABLE or estimate.duration_minutes is None:
        return estimate
    duration = estimate.duration_minutes
    precision = estimate.precision
    if precision == RoutePrecision.UNKNOWN:
        precision = _query_precision(query)
    confidence = estimate.confidence
    if confidence == RouteConfidence.LOW and estimate.provider == "google-routes":
        confidence = (
            RouteConfidence.HIGH if precision == RoutePrecision.ADDRESS else RouteConfidence.MEDIUM
        )
    return estimate.model_copy(
        update={
            "duration_low_minutes": estimate.duration_low_minutes or duration,
            "duration_high_minutes": estimate.duration_high_minutes or duration,
            "sample_minutes": estimate.sample_minutes or [duration],
            "precision": precision,
            "confidence": confidence,
            "origin_resolved": estimate.origin_resolved or query.origin,
            "destination_resolved": estimate.destination_resolved or query.destination,
            "origin_precision": (
                estimate.origin_precision
                if estimate.origin_precision != RoutePrecision.UNKNOWN
                else _label_precision(query.origin)
            ),
            "destination_precision": (
                estimate.destination_precision
                if estimate.destination_precision != RoutePrecision.UNKNOWN
                else _label_precision(query.destination)
            ),
            "route_scope": (
                estimate.route_scope if estimate.route_scope != "unknown" else _route_scope(query)
            ),
        }
    )


def _plausibility_issue(
    query: TravelQuery,
    estimate: TravelEstimate,
    place_index: OfflinePlaceIndex,
) -> str | None:
    if estimate.status != CommuteStatus.AVAILABLE or estimate.duration_minutes is None:
        return None
    origin = _resolve_city_component(place_index, query.origin)
    destination = _resolve_city_component(place_index, query.destination)
    if origin is None or destination is None:
        return None
    distance = straight_line_distance_km(origin, destination)
    if distance < 1:
        return None
    minutes = estimate.duration_minutes
    fastest_kmh = {
        TravelMode.TRANSIT: 220,
        TravelMode.CAR: 180,
        TravelMode.BICYCLE: 55,
        TravelMode.WALK: 12,
    }[query.mode]
    minimum = max(1, round(distance / fastest_kmh * 60 * 0.75))
    maximum = {
        TravelMode.TRANSIT: max(150, round(distance * 5 + 45)),
        TravelMode.CAR: max(120, round(distance * 3 + 30)),
        TravelMode.BICYCLE: max(90, round(distance * 5 + 30)),
        TravelMode.WALK: max(120, round(distance * 20 + 30)),
    }[query.mode]
    if minutes < minimum:
        return (
            f"{minutes} min is implausibly short for approximately {distance:.0f} km "
            f"straight-line distance (minimum sanity bound {minimum} min)."
        )
    if minutes > maximum:
        return (
            f"{minutes} min is an extreme outlier for approximately {distance:.0f} km "
            f"straight-line distance (maximum sanity bound {maximum} min)."
        )
    return None


def _rejected_estimate(estimate: TravelEstimate, issue: str) -> TravelEstimate:
    return estimate.model_copy(
        update={
            "status": CommuteStatus.PROVIDER_ERROR,
            "duration_minutes": None,
            "duration_low_minutes": None,
            "duration_high_minutes": None,
            "sample_minutes": [],
            "confidence": RouteConfidence.LOW,
            "message": "The provider result failed a route plausibility check and was not scored.",
            "cache_permitted": False,
            "attempts": [*estimate.attempts, f"Provider result rejected: {issue}"],
        }
    )


def _resolve_city_component(
    place_index: OfflinePlaceIndex,
    label: str,
):
    candidates = [label]
    parts = [part.strip() for part in re.split(r"[,;|]", label) if part.strip()]
    candidates.extend(reversed(parts))
    candidates.extend(re.sub(r"\b\d{4,5}\b", "", part).strip() for part in parts)
    for candidate in candidates:
        if candidate and (resolved := place_index.resolve(candidate)) is not None:
            return resolved
    return None


def mobility_request_from_profile(
    profile: CandidateProfile,
) -> tuple[str, list[tuple[ProfileFact, TravelMode, int]]] | None:
    confirmed = profile.confirmed_facts
    origin_facts = [
        fact
        for fact in confirmed
        if fact.key in {"location.origin", "commute.origin", "mobility.origin"}
    ]
    origin_fact = (
        max(origin_facts, key=lambda fact: _precision_rank(_label_precision(str(fact.value))))
        if origin_facts
        else None
    )
    origin = str(origin_fact.value) if origin_fact is not None else None
    if not origin and profile.location is not None:
        origin = profile.location.origin_label
    if not origin:
        return None

    constraints: list[tuple[ProfileFact, TravelMode, int]] = []
    for fact in confirmed:
        limit = mobility_limit_from_fact(fact)
        if limit is None:
            continue
        mode, maximum_minutes = limit
        constraints.append((fact, mode, min(360, maximum_minutes)))
    if not constraints:
        return None
    return origin, constraints


def routing_destinations_from_job(job: JobPosting) -> list[str]:
    """Derive every distinct physical workplace evidenced by an advertisement."""

    if _job_is_remote_only(job):
        # A company seat is not a commute destination for a remote-only role.
        # Returning before any resolver/provider work avoids several sequential
        # geocoding and routing timeouts for labels such as "Remote – Europe".
        return []

    location_keys = {
        "location.address",
        "job.location.address",
        "location.postal_code",
        "job.location.postal_code",
        "office.location",
        "workplace.location",
    }
    candidates = [job.location]
    candidates.extend(fact.value for fact in job.facts if fact.key in location_keys)
    split_candidates = [
        part
        for value in candidates
        if value.strip()
        for part in _split_advertised_locations(value)
        if _physical_destination(part)
    ]
    distinct: list[str] = []
    seen_labels: set[str] = set()
    for candidate in split_candidates:
        identity = " ".join(candidate.casefold().split())
        if identity not in seen_labels:
            seen_labels.add(identity)
            distinct.append(candidate)

    described = [
        (candidate, _label_precision(candidate), _routing_city_identity(candidate))
        for candidate in distinct
    ]
    precise_city_identities = {
        city_identity
        for _, precision, city_identity in described
        if precision != RoutePrecision.CITY_TO_CITY and city_identity is not None
    }
    precise_by_city: dict[tuple[str, str], list[str]] = {}
    for candidate, precision, city_identity in described:
        if precision != RoutePrecision.CITY_TO_CITY and city_identity is not None:
            precise_by_city.setdefault(city_identity, []).append(candidate)
    selected: list[str] = []
    seen_generic_cities: set[tuple[str, str]] = set()
    emitted_precise_labels: set[str] = set()
    for candidate, precision, city_identity in described:
        if precision != RoutePrecision.CITY_TO_CITY:
            # Different addresses, postcodes, districts, and stations remain
            # distinct even when they belong to the same city. Their commute
            # times can differ materially.
            identity = " ".join(candidate.casefold().split())
            if identity not in emitted_precise_labels:
                selected.append(candidate)
                emitted_precise_labels.add(identity)
            continue
        if city_identity is not None and city_identity in precise_city_identities:
            # A city-level display label is only a fallback. Once the ad also
            # provides a precise workplace in that city, route the precise
            # evidence instead of routing both to competing approximations.
            for precise_candidate in precise_by_city[city_identity]:
                identity = " ".join(precise_candidate.casefold().split())
                if identity not in emitted_precise_labels:
                    selected.append(precise_candidate)
                    emitted_precise_labels.add(identity)
            continue
        generic_identity = city_identity or ("", " ".join(candidate.casefold().split()))
        if generic_identity in seen_generic_cities:
            continue
        seen_generic_cities.add(generic_identity)
        selected.append(candidate)
    return selected


def routing_destination_from_job(job: JobPosting) -> str:
    """Return the first route candidate for compatibility with older adapters."""

    destinations = routing_destinations_from_job(job)
    return destinations[0] if destinations else "Unknown"


def _split_advertised_locations(value: str) -> list[str]:
    parts = re.split(
        r"\s+/\s+|\s*\|\s*|\s*;\s*|[\r\n•]+",
        value.strip(),
    )
    return [" ".join(part.strip(" ,").split()) for part in parts if part.strip(" ,")]


def _routing_city_identity(label: str) -> tuple[str, str] | None:
    """Resolve a city only from a trustworthy city-bearing portion of a label.

    Full street labels are deliberately not passed through the place index: a
    street name can itself equal an unrelated city (for example Landstrasse in
    Vienna). A postcode or an explicit comma-separated city suffix is a safer
    grouping signal. A failed resolution merely keeps an extra route candidate.
    """

    precision = _label_precision(label)
    if postal := _ROUTING_POSTAL_INDEX.resolve(label):
        city_label = re.sub(
            rf"^\s*{re.escape(postal.postal_code)}\s*",
            "",
            postal.label,
        ).strip()
        if city_label and (
            resolved := _ROUTING_PLACE_INDEX.resolve(city_label, postal.country_code)
        ):
            return resolved.country_code, resolved.label.casefold()

    if precision == RoutePrecision.CITY_TO_CITY:
        resolved = _ROUTING_PLACE_INDEX.resolve(label)
        return (resolved.country_code, resolved.label.casefold()) if resolved is not None else None

    comma_parts = [part.strip() for part in label.split(",") if part.strip()]
    for part in reversed(comma_parts[1:]):
        city_label = re.sub(r"\b\d{4,5}\b", "", part).strip(" ,")
        if not city_label or city_label.casefold() in {
            "de",
            "germany",
            "deutschland",
        }:
            continue
        resolved = _ROUTING_PLACE_INDEX.resolve(city_label)
        if resolved is not None:
            return resolved.country_code, resolved.label.casefold()

    if precision in {RoutePrecision.DISTRICT, RoutePrecision.RAIL_HUB}:
        resolved = _ROUTING_PLACE_INDEX.resolve(label)
        if resolved is not None:
            return resolved.country_code, resolved.label.casefold()
    return None


def _physical_destination(value: str) -> bool:
    material = " ".join(value.casefold().replace("-", " ").split())
    if not material or material == "unknown":
        return False
    return not bool(
        re.fullmatch(
            r"(?:fully\s+)?remote(?:\s+(?:within|in)\s+.+)?|"
            r"home\s*office|homeoffice|anywhere|worldwide|"
            r"deutschlandweit|germany\s*wide|hybrid",
            material,
        )
    )


def _job_is_remote_only(job: JobPosting) -> bool:
    """Use explicit job evidence to distinguish remote-only from hybrid roles."""

    remote_facts = [
        fact.value
        for fact in job.facts
        if fact.key in {"work_model.remote", "job.work_model.remote"}
    ]
    if any(_remote_only_label(value) for value in remote_facts):
        return True
    # Location-only detection stays conservative when multiple alternatives
    # are advertised: "Berlin / Remote" still retains Berlin as routable.
    return "/" not in job.location and _remote_only_label(job.location)


def _remote_only_label(value: str) -> bool:
    material = " ".join(value.casefold().replace("_", " ").split())
    if not material or "hybrid" in material or "on site" in material or "onsite" in material:
        return False
    if "homeoffice" in material or "home office" in material or "work from anywhere" in material:
        return True
    if not re.search(r"\bremote\b", material):
        return False
    return bool(
        re.fullmatch(
            r"(?:100\s*%\s*)?(?:fully\s+)?remote(?:\s+only)?"
            r"(?:\s*[-–—,:|()]\s*|\s+(?:within|in|from)\s+)?[\wÀ-ɏ .()/-]*|"
            r"[\wÀ-ɏ .()/-]+\s*[-–—,:|()]\s*(?:100\s*%\s*)?(?:fully\s+)?remote",
            material,
            flags=re.UNICODE,
        )
    )


def _normalized_routing_destinations(
    value: str | Sequence[str],
) -> tuple[list[str], int]:
    values = [value] if isinstance(value, str) else list(value)
    unique: list[str] = []
    seen: set[str] = set()
    for item in values:
        clean = " ".join(str(item).split())
        identity = clean.casefold()
        if _physical_destination(clean) and identity not in seen:
            seen.add(identity)
            unique.append(clean)
    routed = unique[:_MAX_ROUTED_DESTINATIONS]
    return routed, len(unique) - len(routed)


def _select_destination_assessment(
    candidates: list[CommuteAssessment],
    destinations: list[str],
    *,
    omitted_destination_count: int = 0,
) -> CommuteAssessment:
    available = [
        item
        for item in candidates
        if item.estimate.status == CommuteStatus.AVAILABLE
        and item.estimate.duration_minutes is not None
    ]
    confidence_rank = {
        RouteConfidence.HIGH: 0,
        RouteConfidence.MEDIUM: 1,
        RouteConfidence.LOW: 2,
    }
    if available:
        selected = min(
            available,
            key=lambda item: (
                item.estimate.duration_minutes or 10**9,
                confidence_rank[item.estimate.confidence],
                -_precision_rank(item.estimate.destination_precision),
                destinations.index(item.destination),
            ),
        )
    else:
        status_rank = {
            CommuteStatus.NEEDS_PRECISE_LOCATION: 0,
            CommuteStatus.PROVIDER_UNAVAILABLE: 1,
            CommuteStatus.PROVIDER_ERROR: 2,
            CommuteStatus.NO_ROUTE: 3,
            CommuteStatus.AVAILABLE: 4,
        }
        selected = min(
            candidates,
            key=lambda item: (
                status_rank[item.estimate.status],
                destinations.index(item.destination),
            ),
        )
    unresolved = [
        item.destination
        for item in candidates
        if item.estimate.status
        in {
            CommuteStatus.PROVIDER_ERROR,
            CommuteStatus.PROVIDER_UNAVAILABLE,
            CommuteStatus.NEEDS_PRECISE_LOCATION,
        }
    ]
    estimate = selected.estimate
    total_destination_count = len(destinations) + omitted_destination_count
    if total_destination_count > 1:
        checked_scope = (
            f"{len(destinations)} of {total_destination_count}"
            if omitted_destination_count
            else str(len(destinations))
        )
        if available:
            note = (
                f"Compared routes for {checked_scope} advertised workplace locations. "
                "The selected route is the shortest confirmed available result."
            )
        else:
            note = (
                f"Checked routing for {checked_scope} advertised workplace locations. "
                "No available route was confirmed."
            )
        unresolved_count = len(unresolved) + omitted_destination_count
        if unresolved_count:
            note += (
                f" {unresolved_count} alternative location(s) could not be fully evaluated; "
                "an over-limit result is therefore not treated as a proven conflict."
            )
        combined_message = " ".join(
            part.strip() for part in (note, estimate.message or "") if part.strip()
        )[:1_000].rstrip()
        estimate = estimate.model_copy(update={"message": combined_message})
    return selected.model_copy(
        update={
            "estimate": estimate,
            "evaluated_destinations": destinations,
            "unresolved_destinations": unresolved,
            "omitted_destination_count": omitted_destination_count,
        }
    )


def _company_destination_search_hint(company: str | None, destination: str) -> str | None:
    """Give POI-capable providers a bounded employer-location hint.

    The hint is deliberately separate from the evidence-backed destination.
    Transitous continues to route the verified city/address itself; Google may
    resolve a company POI when no street or postcode was exposed by the ad.
    """

    if not company or company.casefold() in {"unknown", "employer not stated"}:
        return None
    if _label_precision(destination) not in {
        RoutePrecision.CITY_TO_CITY,
        RoutePrecision.DISTRICT,
    }:
        return None
    return f"{company.strip()}, {destination}"


def _precision_rank(precision: RoutePrecision) -> int:
    return {
        RoutePrecision.UNKNOWN: 0,
        RoutePrecision.CITY_TO_CITY: 1,
        RoutePrecision.RAIL_HUB: 2,
        RoutePrecision.DISTRICT: 3,
        RoutePrecision.POSTAL_CODE: 4,
        RoutePrecision.ADDRESS: 5,
    }[precision]


def query_fingerprint(query: TravelQuery) -> str:
    departure_bucket = (
        query.departure_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
        if query.departure_at
        else "any"
    )
    material = "|".join(
        (
            "mobility-v0.6.9",
            " ".join(query.origin.casefold().split()),
            " ".join(query.destination.casefold().split()),
            " ".join((query.destination_search_hint or "").casefold().split()),
            query.mode.value,
            departure_bucket,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _duration_seconds(value: str) -> int | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)s", value.strip())
    return round(float(match.group(1))) if match else None


def _ors_attribution() -> str:
    return "© openrouteservice.org by HeiGIT | Map data © OpenStreetMap contributors"


def _valhalla_attribution() -> str:
    return "Routing © FOSSGIS e.V. | Map data © OpenStreetMap contributors"


def _open_route_error_diagnostic(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, (KeyError, TypeError, ValueError)) and str(exc):
        return f"{type(exc).__name__}: {str(exc)[:300]}"
    return type(exc).__name__


def _transitous_attribution() -> str:
    return "Transitous / MOTIS · community public-transport data"


def _provider_attribution(provider: str) -> tuple[str | None, str | None]:
    if provider == "google-routes":
        return "Google Maps", "https://www.google.com/maps"
    if provider == "openrouteservice":
        return _ors_attribution(), "https://openrouteservice.org/"
    if provider == "valhalla-osm":
        return (
            _valhalla_attribution(),
            "https://fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen/",
        )
    if provider == "transitous":
        return _transitous_attribution(), "https://transitous.org/"
    return None, None


def _stored_samples(value: str | None, fallback: int | None) -> list[int]:
    if value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [int(item) for item in parsed if isinstance(item, (int, float)) and item > 0]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return [fallback] if fallback is not None else []


def _stored_precision(
    value: str | None,
    query: TravelQuery,
    provider: str,
) -> RoutePrecision:
    try:
        return RoutePrecision(value) if value else _legacy_precision(query, provider)
    except ValueError:
        return _legacy_precision(query, provider)


def _legacy_precision(query: TravelQuery, provider: str) -> RoutePrecision:
    if provider == "transitous" and _city_level_pair(query):
        return RoutePrecision.RAIL_HUB
    return _query_precision(query)


def _stored_confidence(value: str | None) -> RouteConfidence:
    try:
        return RouteConfidence(value) if value else RouteConfidence.LOW
    except ValueError:
        return RouteConfidence.LOW


def _stored_endpoint_precision(
    value: str | None,
    label: str,
    provider: str,
) -> RoutePrecision:
    try:
        return RoutePrecision(value) if value else _legacy_endpoint_precision(label, provider)
    except ValueError:
        return _legacy_endpoint_precision(label, provider)


def _legacy_endpoint_precision(label: str, provider: str) -> RoutePrecision:
    if provider == "transitous" and _is_city_level_label(label):
        return RoutePrecision.RAIL_HUB
    return _label_precision(label)


def _next_peak_departure(now: datetime | None = None) -> datetime:
    """Return the next ordinary Tuesday at 08:00 in the German local timezone."""

    berlin = ZoneInfo("Europe/Berlin")
    current = (now or datetime.now(timezone.utc)).astimezone(berlin)
    days_until_tuesday = (1 - current.weekday()) % 7
    candidate = (current + timedelta(days=days_until_tuesday)).replace(
        hour=8,
        minute=0,
        second=0,
        microsecond=0,
    )
    if candidate <= current:
        candidate += timedelta(days=7)
    while _is_german_public_holiday(candidate.date()):
        candidate += timedelta(days=7)
    return candidate


def _same_city_precision_estimate(
    query: TravelQuery,
    *,
    place_index: OfflinePlaceIndex,
) -> TravelEstimate | None:
    if not _city_level_pair(query):
        return None
    origin = place_index.resolve(query.origin)
    destination = place_index.resolve(query.destination)
    if origin is None or destination is None:
        return None
    if origin.country_code != destination.country_code or origin.label != destination.label:
        return None
    return TravelEstimate(
        status=CommuteStatus.NEEDS_PRECISE_LOCATION,
        provider="location-precision",
        message=(
            "This is a same-city match, but both endpoints are only city-level. Add a district, "
            "postcode, station, or street in Compass or the job location before using commute time."
        ),
        cache_permitted=False,
        attempts=[
            f"Offline place resolution mapped both endpoints to {origin.label}, {origin.country_code}."
        ],
        precision=RoutePrecision.CITY_TO_CITY,
        confidence=RouteConfidence.LOW,
        origin_resolved=f"{origin.label}, {origin.country_code}",
        destination_resolved=f"{destination.label}, {destination.country_code}",
        origin_precision=RoutePrecision.CITY_TO_CITY,
        destination_precision=RoutePrecision.CITY_TO_CITY,
        route_scope="same_city_unknown_endpoints",
    )


def _query_precision(query: TravelQuery) -> RoutePrecision:
    if _city_level_pair(query):
        return RoutePrecision.CITY_TO_CITY
    precisions = {_label_precision(query.origin), _label_precision(query.destination)}
    if RoutePrecision.CITY_TO_CITY in precisions:
        return RoutePrecision.CITY_TO_CITY
    if RoutePrecision.DISTRICT in precisions:
        return RoutePrecision.DISTRICT
    if RoutePrecision.POSTAL_CODE in precisions:
        return RoutePrecision.POSTAL_CODE
    return RoutePrecision.ADDRESS


def _label_precision(label: str) -> RoutePrecision:
    material = " ".join(label.casefold().split())
    station_markers = ("bahnhof", "hauptbahnhof", " hbf", "station")
    if any(marker in material for marker in station_markers):
        return RoutePrecision.RAIL_HUB
    if re.search(r"\b\d{4,5}\b", material):
        street_markers = (
            "straße",
            "strasse",
            "street",
            "road",
            "allee",
            "weg",
            "platz",
        )
        return (
            RoutePrecision.ADDRESS
            if any(marker in material for marker in street_markers)
            else RoutePrecision.POSTAL_CODE
        )
    district_markers = ("district", "stadtteil", "borough", "quartier")
    if any(marker in material for marker in district_markers):
        return RoutePrecision.DISTRICT
    return RoutePrecision.CITY_TO_CITY


def _nominatim_candidate_is_safe(label: str, candidate: dict[str, object]) -> bool:
    try:
        latitude = float(candidate["lat"])
        longitude = float(candidate["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return False
    query_tokens = _normalized_location_tokens(label)
    material = " ".join(
        (
            str(candidate.get("display_name") or ""),
            " ".join(
                str(value)
                for value in (
                    candidate.get("address") if isinstance(candidate.get("address"), dict) else {}
                ).values()
            ),
        )
    )
    candidate_tokens = _normalized_location_tokens(material)
    meaningful = {
        token
        for token in query_tokens
        if token not in {"am", "an", "der", "de", "the", "germany", "deutschland"}
    }
    if not meaningful:
        return False
    matched = meaningful.intersection(candidate_tokens)
    required_ratio = 1.0 if len(meaningful) <= 2 else 0.67
    if len(matched) / len(meaningful) < required_ratio:
        return False
    postal_tokens = {token for token in meaningful if token.isdigit() and len(token) == 5}
    return postal_tokens.issubset(candidate_tokens)


def _nominatim_candidate_score(label: str, candidate: dict[str, object]) -> tuple[float, int]:
    query_tokens = _normalized_location_tokens(label)
    candidate_tokens = _normalized_location_tokens(str(candidate.get("display_name") or ""))
    overlap = len(query_tokens.intersection(candidate_tokens)) / max(1, len(query_tokens))
    return overlap, _precision_rank(_nominatim_precision(candidate))


def _nominatim_precision(candidate: dict[str, object]) -> RoutePrecision:
    category = str(candidate.get("addresstype") or candidate.get("type") or "").casefold()
    if category in {"house", "building", "road", "residential", "commercial"}:
        return RoutePrecision.ADDRESS
    if category in {"postcode"}:
        return RoutePrecision.POSTAL_CODE
    if category in {
        "borough",
        "city_district",
        "district",
        "neighbourhood",
        "quarter",
        "suburb",
    }:
        return RoutePrecision.DISTRICT
    return RoutePrecision.CITY_TO_CITY


def _normalized_location_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return set(re.findall(r"[a-z0-9]+", ascii_text))


def _route_scope(query: TravelQuery) -> str:
    if query.mode == TravelMode.TRANSIT:
        origin_is_city = _is_city_level_label(query.origin)
        destination_is_city = _is_city_level_label(query.destination)
        if origin_is_city and destination_is_city:
            return "station_to_station"
        if origin_is_city:
            return "station_to_door"
        if destination_is_city:
            return "door_to_station"
    if _query_precision(query) == RoutePrecision.ADDRESS:
        return "door_to_door"
    return "area_to_area"


def _city_level_pair(query: TravelQuery) -> bool:
    return _is_city_level_label(query.origin) and _is_city_level_label(query.destination)


def _is_city_level_label(label: str) -> bool:
    material = " ".join(label.casefold().split())
    if re.search(r"\b\d{4,5}\b", material) or re.search(r"\d", material):
        return False
    address_markers = (
        "straße",
        "strasse",
        "street",
        "road",
        "allee",
        "weg",
        "platz",
        "station",
        "bahnhof",
        " hbf",
        "district",
        "stadtteil",
    )
    return not any(marker in material for marker in address_markers)


def _coordinate_distance_km(origin: TransitousPlace, destination: TransitousPlace) -> float:
    from .geography import ResolvedPlace

    return straight_line_distance_km(
        ResolvedPlace(
            label=origin.display_name,
            country_code="",
            latitude=origin.lat,
            longitude=origin.lon,
        ),
        ResolvedPlace(
            label=destination.display_name,
            country_code="",
            latitude=destination.lat,
            longitude=destination.lon,
        ),
    )


def _is_german_public_holiday(day: date) -> bool:
    """Cover nationwide German holidays; state-only holidays remain provider reality."""

    easter_sunday = _easter_sunday(day.year)
    movable = {
        easter_sunday - timedelta(days=2),
        easter_sunday + timedelta(days=1),
        easter_sunday + timedelta(days=39),
        easter_sunday + timedelta(days=50),
    }
    fixed = {
        date(day.year, 1, 1),
        date(day.year, 5, 1),
        date(day.year, 10, 3),
        date(day.year, 12, 25),
        date(day.year, 12, 26),
    }
    return day in fixed or day in movable


def _easter_sunday(year: int) -> date:
    """Gregorian computus used only to avoid nationwide movable holidays."""

    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def structured_constraint_fact_id(profile: CandidateProfile, mode: TravelMode) -> UUID:
    """Stable identity for future structured-only constraints."""

    return uuid5(profile.id, f"commute:{mode.value}")
