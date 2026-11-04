"""Offline, transparent place resolution for Explore result ordering."""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from functools import cached_property, lru_cache
from importlib import resources
from io import TextIOWrapper
from typing import Literal
from zipfile import ZipFile

import geonamescache
from pydantic import Field

from .profile import StrictModel


class ResolvedPlace(StrictModel):
    label: str
    country_code: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ResolvedPostalCode(ResolvedPlace):
    postal_code: str = Field(pattern=r"^\d{5}$")
    accuracy: int = Field(default=0, ge=0, le=6)


class NutsRegion(StrictModel):
    """An official NUTS 2024 classification entry, without boundary geometry."""

    code: str
    label: str
    country_code: str


class ResolvedNutsRepresentativePoint(ResolvedPlace):
    """A city point used only to order Explore results for a NUTS region.

    This is neither a region centroid nor a workplace coordinate. Keeping the
    precision and source identity on the value makes the approximation
    inspectable and prevents callers from treating it as exact route input.
    """

    nuts_code: str
    region_label: str
    geoname_id: int = Field(ge=1)
    precision: Literal["regional_representative"] = "regional_representative"


class OfflineNutsRegionIndex:
    """Resolve official Eurostat NUTS 2024 region codes without a network call.

    NUTS is hierarchical: the two-letter country unit is followed by up to
    three regional levels. The bundled table contains only official codes and
    names from the NUTS 2024 legal classification. It deliberately contains no
    GISCO boundary geometry or derived centroids.
    """

    @cached_property
    def _regions(self) -> list[NutsRegion]:
        table_resource = resources.files("betteroption").joinpath("data/nuts-2024.csv")
        with resources.as_file(table_resource) as table_path:
            with table_path.open(encoding="utf-8", newline="") as table_file:
                rows = csv.DictReader(table_file)
                return [
                    NutsRegion(
                        code=str(row["nuts_id"]).upper(),
                        label=str(row["name"]),
                        country_code=_iso_country_code(str(row["country_code"])),
                    )
                    for row in rows
                ]

    @cached_property
    def _by_code(self) -> dict[str, NutsRegion]:
        return {region.code: region for region in self._regions}

    @cached_property
    def _by_name(self) -> dict[str, list[NutsRegion]]:
        names: dict[str, list[NutsRegion]] = {}
        for region in self._regions:
            normalized = _normalize_place(region.label)
            if normalized:
                names.setdefault(normalized, []).append(region)
        return names

    @lru_cache(maxsize=4_096)
    def resolve_code(self, code: str) -> NutsRegion | None:
        """Resolve a NUTS 0-3 code such as ``DE724``."""

        return self._by_code.get(code.strip().upper())

    @lru_cache(maxsize=4_096)
    def resolve_name(
        self,
        label: str,
        preferred_country_code: str = "",
    ) -> NutsRegion | None:
        """Resolve an exact official NUTS region name.

        A name can legitimately exist at several hierarchy levels. Prefer
        the caller's country and then the most specific unit; that label is
        the best available input for the separate approximate place resolver.
        """

        clean = " ".join(label.split())
        parts = [part.strip() for part in re.split(r"[,;|]", clean) if part.strip()]
        candidates: list[NutsRegion] = []
        # Country suffixes are common in provider output, while a few official
        # NUTS names themselves contain commas. Try the longest prefix first so
        # ``Kaiserslautern, Kreisfreie Stadt, Germany`` retains its full name.
        for end in range(len(parts), 0, -1):
            candidate_label = ", ".join(parts[:end])
            candidates = self._by_name.get(_normalize_place(candidate_label), [])
            if candidates:
                break
        if not candidates:
            return None
        preferred = _iso_country_code(preferred_country_code.strip().upper())
        return max(
            candidates,
            key=lambda region: (
                region.country_code == preferred if preferred else False,
                len(region.code),
            ),
        )


_NUTS_REGION_INDEX = OfflineNutsRegionIndex()


class OfflineNutsRepresentativePointIndex:
    """Load a small, versioned NUTS-to-GeoNames Explore crosswalk.

    The crosswalk is deliberately separate from :class:`OfflinePlaceIndex`.
    Exact city resolution and all routing therefore remain unable to consume a
    regional proxy accidentally.
    """

    @cached_property
    def _points(self) -> list[ResolvedNutsRepresentativePoint]:
        table_resource = resources.files("betteroption").joinpath(
            "data/nuts-representative-points-2024.csv"
        )
        with resources.as_file(table_resource) as table_path:
            with table_path.open(encoding="utf-8", newline="") as table_file:
                rows = csv.DictReader(table_file)
                points: list[ResolvedNutsRepresentativePoint] = []
                for row in rows:
                    code = str(row["nuts_id"]).strip().upper()
                    region = _NUTS_REGION_INDEX.resolve_code(code)
                    if region is None:
                        continue
                    country_code = _iso_country_code(str(row["country_code"]))
                    region_label = str(row["region_name"]).strip()
                    if country_code != region.country_code or _normalize_place(
                        region_label
                    ) != _normalize_place(region.label):
                        continue
                    points.append(
                        ResolvedNutsRepresentativePoint(
                            label=str(row["representative_place"]).strip(),
                            country_code=country_code,
                            latitude=float(row["latitude"]),
                            longitude=float(row["longitude"]),
                            nuts_code=code,
                            region_label=region.label,
                            geoname_id=int(row["geoname_id"]),
                            precision="regional_representative",
                        )
                    )
                return points

    @cached_property
    def _by_code(self) -> dict[str, ResolvedNutsRepresentativePoint]:
        return {point.nuts_code: point for point in self._points}

    @lru_cache(maxsize=1_024)
    def resolve_code(self, code: str) -> ResolvedNutsRepresentativePoint | None:
        return self._by_code.get(code.strip().upper())

    @lru_cache(maxsize=1_024)
    def resolve_region(
        self,
        label: str,
        preferred_country_code: str = "",
    ) -> ResolvedNutsRepresentativePoint | None:
        region = _NUTS_REGION_INDEX.resolve_name(label, preferred_country_code)
        return self.resolve_code(region.code) if region is not None else None


_NUTS_REPRESENTATIVE_POINT_INDEX = OfflineNutsRepresentativePointIndex()


class OfflinePlaceIndex:
    """Resolve city labels from the bundled GeoNames subset without API calls."""

    @cached_property
    def _cities(self) -> list[dict[str, object]]:
        cache = geonamescache.GeonamesCache(min_city_population=15_000)
        return list(cache.get_cities().values())

    @cached_property
    def _names(self) -> dict[str, list[dict[str, object]]]:
        names: dict[str, list[dict[str, object]]] = {}
        for city in self._cities:
            candidates = [str(city.get("name") or ""), *city.get("alternatenames", [])]
            for candidate in candidates:
                normalized = _normalize_place(candidate)
                if normalized:
                    names.setdefault(normalized, []).append(city)
        return names

    @lru_cache(maxsize=4_096)
    def resolve(
        self,
        label: str,
        preferred_country_code: str = "",
    ) -> ResolvedPlace | None:
        clean = " ".join(label.split())
        if not clean or clean.casefold() in {"unknown", "location not stated"}:
            return None
        city_label = re.split(r"[,;|]", clean, maxsplit=1)[0]
        normalized = _normalize_place(city_label)
        candidates = self._names.get(normalized, [])
        if not candidates:
            # Resolve appended district/station text through bounded n-gram
            # lookups. The previous implementation scanned every known city
            # alias for every result, which made a 100-card Explore run take
            # several minutes.
            tokens = normalized.split()
            matches: list[tuple[int, int, list[dict[str, object]]]] = []
            maximum_size = min(5, len(tokens))
            for size in range(maximum_size, 0, -1):
                for start in range(0, len(tokens) - size + 1):
                    name = " ".join(tokens[start : start + size])
                    if len(name) < 4:
                        continue
                    items = self._names.get(name)
                    if items:
                        matches.append((size, -start, items))
                if matches:
                    break
            if matches:
                _, _, candidates = max(
                    matches,
                    key=lambda item: (
                        item[0],
                        item[1],
                        max(int(city.get("population") or 0) for city in item[2]),
                    ),
                )
        if not candidates:
            return None
        country_hint = _country_hint(clean)
        preferred = preferred_country_code.strip().upper()
        selected = max(
            candidates,
            key=lambda city: (
                str(city.get("countrycode") or "") == country_hint if country_hint else False,
                str(city.get("countrycode") or "") == preferred if preferred else False,
                int(city.get("population") or 0),
            ),
        )
        return ResolvedPlace(
            label=str(selected["name"]),
            country_code=str(selected["countrycode"]),
            latitude=float(selected["latitude"]),
            longitude=float(selected["longitude"]),
        )

    @lru_cache(maxsize=4_096)
    def resolve_for_explore(
        self,
        label: str,
        preferred_country_code: str = "",
    ) -> ResolvedPlace | None:
        """Resolve a place for approximate Explore ordering.

        Exact cities retain normal GeoNames resolution. An exact NUTS code or
        official NUTS label may additionally use the explicitly marked
        representative-city crosswalk. Callers that perform route calculation
        must use :meth:`resolve`, which never accepts those regional proxies.
        """

        clean = " ".join(label.split())
        if not clean:
            return None
        code_match = re.fullmatch(r"[A-Za-z]{2}[A-Za-z0-9]{0,3}", clean)
        if code_match and _NUTS_REGION_INDEX.resolve_code(clean) is not None:
            return _NUTS_REPRESENTATIVE_POINT_INDEX.resolve_code(clean)

        country_hint = _country_hint(clean) or preferred_country_code.strip().upper()
        regional_point = _NUTS_REPRESENTATIVE_POINT_INDEX.resolve_region(
            clean,
            country_hint,
        )
        if regional_point is not None:
            return regional_point
        return self.resolve(clean, preferred_country_code)

    @lru_cache(maxsize=256)
    def nearby(
        self,
        label: str,
        *,
        maximum_distance_km: float = 120,
        limit: int = 8,
    ) -> list[ResolvedPlace]:
        """Return nearby city search anchors without a network or routing request."""

        origin = self.resolve(label)
        if origin is None or limit <= 0:
            return []
        candidates: list[tuple[float, float, ResolvedPlace]] = []
        seen: set[tuple[str, str]] = set()
        for city in self._cities:
            country_code = str(city.get("countrycode") or "")
            name = str(city.get("name") or "").strip()
            if not name or country_code != origin.country_code:
                continue
            identity = (country_code, _normalize_place(name))
            if identity in seen:
                continue
            seen.add(identity)
            place = ResolvedPlace(
                label=name,
                country_code=country_code,
                latitude=float(city["latitude"]),
                longitude=float(city["longitude"]),
            )
            distance = straight_line_distance_km(origin, place)
            if distance > maximum_distance_km:
                continue
            population = int(city.get("population") or 0)
            # Search anchors should cover meaningful regional labour markets, not
            # only the closest small suburb. Population is discounted smoothly by
            # distance, producing a generic metropolitan mix without city-specific rules.
            regional_weight = population / ((1 + distance / 35) ** 1.25)
            candidates.append((-regional_weight, distance, place))
        candidates.sort(key=lambda item: (item[0], item[1], item[2].label.casefold()))
        return [place for _, _, place in candidates[:limit]]


class OfflineGermanPostalCodeIndex:
    """Resolve German postcodes locally from the bundled GeoNames dump.

    The complete country file is downloaded at build time. Runtime lookups do
    not disclose a user's postcode to GeoNames, Transitous, or another
    geocoder. The data is published under CC BY 4.0 by GeoNames.
    """

    @cached_property
    def _postal_codes(self) -> dict[str, list[tuple[str, float, float, int]]]:
        postal_codes: dict[str, list[tuple[str, float, float, int]]] = {}
        archive_resource = resources.files("betteroption").joinpath("data/geonames-DE-postal.zip")
        with resources.as_file(archive_resource) as archive_path:
            with ZipFile(archive_path) as archive:
                with archive.open("DE.txt") as binary_file:
                    with TextIOWrapper(binary_file, encoding="utf-8") as text_file:
                        for row in csv.reader(text_file, delimiter="\t"):
                            if len(row) < 12 or row[0] != "DE" or not row[1].isdigit():
                                continue
                            try:
                                latitude = float(row[9])
                                longitude = float(row[10])
                                accuracy = int(row[11] or 0)
                            except ValueError:
                                continue
                            postal_codes.setdefault(row[1], []).append(
                                (row[2], latitude, longitude, accuracy)
                            )
        return postal_codes

    @lru_cache(maxsize=2_048)
    def resolve(self, label: str) -> ResolvedPostalCode | None:
        match = re.search(r"(?<!\d)(\d{5})(?!\d)", label)
        if match is None:
            return None
        postal_code = match.group(1)
        candidates = self._postal_codes.get(postal_code, [])
        if not candidates:
            return None
        normalized_label = _normalize_place(label)
        selected = max(
            candidates,
            key=lambda candidate: (
                _normalize_place(candidate[0]) in normalized_label,
                candidate[3],
            ),
        )
        place_name, latitude, longitude, accuracy = selected
        return ResolvedPostalCode(
            label=f"{postal_code} {place_name}",
            country_code="DE",
            postal_code=postal_code,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
        )


def straight_line_distance_km(origin: ResolvedPlace, destination: ResolvedPlace) -> float:
    """Return a Haversine distance used only for Explore ordering."""

    radius_km = 6_371.0088
    origin_lat = math.radians(origin.latitude)
    destination_lat = math.radians(destination.latitude)
    latitude_delta = destination_lat - origin_lat
    longitude_delta = math.radians(destination.longitude - origin.longitude)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(origin_lat) * math.cos(destination_lat) * math.sin(longitude_delta / 2) ** 2
    )
    return round(radius_km * 2 * math.asin(math.sqrt(haversine)), 1)


def _normalize_place(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _country_hint(value: str) -> str | None:
    normalized = _normalize_place(value)
    explicit_aliases = {
        "deutschland": "DE",
        "osterreich": "AT",
        "schweiz": "CH",
        "frankreich": "FR",
        "niederlande": "NL",
    }
    for marker, code in explicit_aliases.items():
        if marker in normalized:
            return code
    countries = geonamescache.GeonamesCache().get_countries()
    for code, country in countries.items():
        names = {
            _normalize_place(str(country.get("name") or "")),
            _normalize_place(str(country.get("iso3") or "")),
        }
        if any(name and name in normalized for name in names):
            return code
    return None


def _iso_country_code(country_code: str) -> str:
    """Translate Eurostat's two legacy spellings to ISO/GeoNames codes."""

    return {"EL": "GR", "UK": "GB"}.get(country_code.upper(), country_code.upper())


_GERMAN_COUNTRY_LABELS = {
    "belgien": "BE",
    "bulgarien": "BG",
    "danemark": "DK",
    "deutschland": "DE",
    "finnland": "FI",
    "frankreich": "FR",
    "griechenland": "GR",
    "grossbritannien": "GB",
    "irland": "IE",
    "italien": "IT",
    "niederlande": "NL",
    "norwegen": "NO",
    "osterreich": "AT",
    "polen": "PL",
    "portugal": "PT",
    "rumanien": "RO",
    "schweden": "SE",
    "schweiz": "CH",
    "slowakei": "SK",
    "spanien": "ES",
    "tschechien": "CZ",
    "ungarn": "HU",
    "vereinigtes konigreich": "GB",
}


@lru_cache(maxsize=512)
def country_code_for_label(label: str) -> str | None:
    """Resolve a standalone ISO, English, or common German country label."""

    normalized = _normalize_place(label)
    if not normalized:
        return None
    countries = geonamescache.GeonamesCache().get_countries()
    if re.fullmatch(r"[a-z]{2}", normalized):
        code = _iso_country_code(normalized.upper())
        return code if code in countries else None
    alias = _GERMAN_COUNTRY_LABELS.get(normalized)
    if alias:
        return alias
    for code, country in countries.items():
        if normalized in {
            _normalize_place(str(country.get("name") or "")),
            _normalize_place(str(country.get("iso3") or "")),
        }:
            return _iso_country_code(code)
    return None


@lru_cache(maxsize=256)
def country_continent_code(country_code: str) -> str | None:
    """Return a GeoNames continent code without imposing a regional default."""

    country = geonamescache.GeonamesCache().get_countries().get(country_code.upper())
    if not country:
        return None
    value = str(country.get("continentcode") or "").strip().upper()
    return value or None


@lru_cache(maxsize=256)
def country_search_terms(country_code: str) -> frozenset[str]:
    """Return generic searchable country identifiers from bundled GeoNames data."""

    country = geonamescache.GeonamesCache().get_countries().get(country_code.upper())
    if not country:
        return frozenset({country_code.casefold()})
    return frozenset(
        value
        for value in {
            country_code.casefold(),
            str(country.get("iso3") or "").strip().casefold(),
            str(country.get("name") or "").strip().casefold(),
        }
        if value
    )
