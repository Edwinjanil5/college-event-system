"""Campus boundary model for location verification.

The campus is described by a constant reference geolocation plus a radius, and
optionally by a verified boundary polygon (GeoJSON) once reliable survey data
exists. The polygon is preferred when it is present and valid; the circular
radius remains the fallback so the system keeps working without survey data.

Nothing in this module proves physical presence. A browser-supplied coordinate
is untrusted input; these helpers only describe how far a reported coordinate
is from the campus description.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Iterable, Sequence

EARTH_RADIUS_M = 6_371_008.8

# GPS outcome vocabulary. INCONCLUSIVE is a first-class outcome, never a
# synonym for MISMATCH: a low-quality reading must not be treated as evidence
# of wrongdoing.
LOCATION_MATCH = 'LOCATION_MATCH'
LOCATION_MISMATCH = 'LOCATION_MISMATCH'
INCONCLUSIVE = 'INCONCLUSIVE'
MISSING = 'MISSING'


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    accuracy_m: float | None = None

    def as_dict(self) -> dict:
        return {
            'latitude': round(self.latitude, 7),
            'longitude': round(self.longitude, 7),
            'accuracy_m': round(self.accuracy_m, 1) if self.accuracy_m is not None else None,
        }


@dataclass(frozen=True)
class GpsResult:
    """Outcome of comparing one reported coordinate with the campus area."""

    status: str
    distance_m: float | None = None
    accuracy_m: float | None = None
    edge_distance_m: float | None = None
    inside: bool | None = None
    reason: str = ''
    boundary_source: str = 'radius'
    captured_at: str | None = None

    @property
    def is_conclusive(self) -> bool:
        return self.status in {LOCATION_MATCH, LOCATION_MISMATCH}

    def as_dict(self) -> dict:
        return {
            'status': self.status,
            # Distance from the campus reference point, always comparable.
            'distance_meters': round(self.distance_m, 1) if self.distance_m is not None else None,
            # Distance from the campus boundary itself.
            'edge_distance_meters': (
                round(self.edge_distance_m, 1) if self.edge_distance_m is not None else None
            ),
            'accuracy_meters': (
                round(self.accuracy_m, 1) if self.accuracy_m is not None else None
            ),
            'inside': self.inside,
            'reason': self.reason,
            'boundary_source': self.boundary_source,
            'captured_at': self.captured_at,
        }


@dataclass
class CampusArea:
    """Describes the campus: a reference point, a radius, and an optional polygon."""

    name: str
    address: str
    latitude: float
    longitude: float
    radius_m: float
    polygon: Sequence[tuple[float, float]] = field(default_factory=tuple)
    polygon_source: str = ''

    @property
    def has_polygon(self) -> bool:
        return len(self.polygon) >= 3

    @property
    def reference(self) -> GeoPoint:
        return GeoPoint(self.latitude, self.longitude)

    @property
    def boundary_source(self) -> str:
        return 'polygon' if self.has_polygon else 'radius'

    def distance_to_centre_m(self, point: GeoPoint) -> float:
        return haversine_m(self.latitude, self.longitude, point.latitude, point.longitude)

    def contains(self, point: GeoPoint) -> bool:
        """Is the reported coordinate inside the campus area?"""
        if self.has_polygon:
            return point_in_polygon(point.latitude, point.longitude, self.polygon)
        return self.distance_to_centre_m(point) <= self.radius_m

    def distance_to_boundary_m(self, point: GeoPoint) -> float:
        """Signed distance to the campus edge (negative when inside)."""
        if self.has_polygon:
            return signed_distance_to_polygon_m(point.latitude, point.longitude, self.polygon)
        return self.distance_to_centre_m(point) - self.radius_m

    def as_dict(self) -> dict:
        return {
            'name': self.name,
            'address': self.address,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'radius_m': self.radius_m,
            'boundary_source': self.boundary_source,
            'has_polygon': self.has_polygon,
        }


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def local_xy_km(latitude: float, longitude: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    """Approximate east/north offsets in kilometres (fine for campus scale)."""
    north = math.radians(latitude - origin_lat) * EARTH_RADIUS_M / 1000.0
    cos_lat = math.cos(math.radians(origin_lat)) or 1e-6
    east = math.radians(longitude - origin_lon) * EARTH_RADIUS_M * cos_lat / 1000.0
    return east, north


def point_in_polygon(latitude: float, longitude: float, polygon: Sequence[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test on (latitude, longitude) vertices."""
    if len(polygon) < 3:
        return False
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        crosses = (lon_i > longitude) != (lon_j > longitude)
        if crosses:
            slope = (lat_j - lat_i) / ((lon_j - lon_i) or 1e-12)
            if latitude < slope * (longitude - lon_i) + lat_i:
                inside = not inside
        j = i
    return inside


def _segment_distance_km(
    lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Distance from a point to a line segment, in a local planar frame."""
    px, py = local_xy_km(lat, lon, lat1, lon1)
    qx, qy = local_xy_km(lat2, lon2, lat1, lon1)
    dx = qx - px
    dy = qy - py
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, -(px * dx + py * dy) / length_sq))
    cx = t * dx
    cy = t * dy
    return math.hypot(px - cx, py - cy)


def signed_distance_to_polygon_m(
    latitude: float, longitude: float, polygon: Sequence[tuple[float, float]]
) -> float:
    """Negative inside the polygon, positive outside, in metres."""
    if len(polygon) < 3:
        return float('nan')
    count = len(polygon)
    best_km = float('inf')
    for index in range(count):
        lat1, lon1 = polygon[index]
        lat2, lon2 = polygon[(index + 1) % count]
        best_km = min(best_km, _segment_distance_km(latitude, longitude, lat1, lon1, lat2, lon2))
    distance_m = best_km * 1000.0
    return -distance_m if point_in_polygon(latitude, longitude, polygon) else distance_m


# ---------------------------------------------------------------------------
# Campus loading
# ---------------------------------------------------------------------------
def load_polygon(path: str | None) -> tuple[tuple[tuple[float, float], ...], str]:
    """Load a campus boundary polygon from a GeoJSON file.

    Returns an empty tuple when no usable polygon exists, so the caller falls
    back to the circular radius. Malformed data is ignored rather than fatal.
    """
    if not path:
        return (), ''
    if not os.path.isfile(path):
        return (), ''
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return (), ''

    coordinates = None
    if isinstance(payload, dict):
        geometry = payload.get('geometry') or payload
        if isinstance(geometry, dict) and geometry.get('type') == 'Polygon':
            coordinates = (geometry.get('coordinates') or [[]])[0]
    elif isinstance(payload, list) and payload:
        coordinates = payload[0]

    vertices: list[tuple[float, float]] = []
    for item in coordinates or []:
        try:
            lon, lat = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            continue
        vertices.append((lat, lon))

    if len(vertices) >= 3 and vertices[0] == vertices[-1]:
        vertices = vertices[:-1]
    if len(vertices) < 3:
        return (), ''
    return tuple(vertices), path


def campus_from_config(config) -> CampusArea:
    """Build the campus area from application configuration."""
    name = config.get('CAMPUS_NAME', 'Campus')
    address = config.get('CAMPUS_ADDRESS', '')
    latitude = float(config.get('CAMPUS_LATITUDE', 0.0))
    longitude = float(config.get('CAMPUS_LONGITUDE', 0.0))
    radius_m = float(config.get('CAMPUS_RADIUS_M', 250.0))
    polygon, source = load_polygon(config.get('CAMPUS_POLYGON_FILE'))
    return CampusArea(
        name=name,
        address=address,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        polygon=polygon,
        polygon_source=source,
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
MAX_PLAUSIBLE_ACCURACY_M = 5_000.0


def validate_coordinate(latitude, longitude) -> tuple[float | None, float | None, str | None]:
    """Parse and range-check submitted coordinates.

    Returns ``(latitude, longitude, error)``. NaN, infinities and out-of-range
    values are rejected instead of silently coerced.
    """
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None, None, 'Coordinates must be numeric.'

    for value, label in ((lat, 'latitude'), (lon, 'longitude')):
        if math.isnan(value) or math.isinf(value):
            return None, None, f'The {label} is not a finite number.'
    if not -90.0 <= lat <= 90.0:
        return None, None, 'Latitude must be between -90 and 90.'
    if not -180.0 <= lon <= 180.0:
        return None, None, 'Longitude must be between -180 and 180.'
    return lat, lon, None


def normalise_accuracy(accuracy) -> tuple[float | None, str | None]:
    """Validate a reported GPS accuracy in metres.

    ``None`` is a legitimate value (the device did not report one). Negative,
    non-finite and absurd values are rejected rather than trusted.
    """
    if accuracy is None or accuracy == '':
        return None, None
    try:
        value = float(accuracy)
    except (TypeError, ValueError):
        return None, None
    if math.isnan(value) or math.isinf(value):
        return None, 'GPS accuracy is not a finite number.'
    if value < 0:
        return None, 'GPS accuracy cannot be negative.'
    if value > MAX_PLAUSIBLE_ACCURACY_M:
        return None, 'Reported GPS accuracy is beyond any plausible range.'
    return value, None


def evaluate_location(
    campus: CampusArea,
    latitude,
    longitude,
    accuracy,
    *,
    max_reliable_accuracy_m: float,
    captured_at: str | None = None,
) -> GpsResult:
    """Compare one reported coordinate with the campus area.

    Produces one of ``LOCATION_MATCH``, ``LOCATION_MISMATCH`` or
    ``INCONCLUSIVE``. An unreadable coordinate is reported as missing so the
    caller can ask for evidence rather than penalise the student.
    """
    lat, lon, error = validate_coordinate(latitude, longitude)
    if error is not None or lat is None:
        return GpsResult(
            status=MISSING,
            reason=error or 'No coordinates were supplied.',
            boundary_source=campus.boundary_source,
            captured_at=captured_at,
        )

    accuracy_m, accuracy_error = normalise_accuracy(accuracy)
    point = GeoPoint(lat, lon, accuracy_m)
    inside = campus.contains(point)
    # Two different, separately meaningful distances:
    #   distance_m       - how far the reading is from the campus reference point
    #   edge_distance_m  - how far it is from the campus boundary itself
    distance_m = campus.distance_to_centre_m(point)
    edge_distance_m = abs(campus.distance_to_boundary_m(point))

    if accuracy_error is not None:
        return GpsResult(
            status=INCONCLUSIVE,
            distance_m=distance_m,
            accuracy_m=None,
            edge_distance_m=edge_distance_m,
            inside=inside,
            reason=accuracy_error,
            boundary_source=campus.boundary_source,
            captured_at=captured_at,
        )

    if accuracy_m is None:
        # No accuracy reported: usable but weaker evidence.
        status = LOCATION_MATCH if inside else LOCATION_MISMATCH
        return GpsResult(
            status=status,
            distance_m=distance_m,
            accuracy_m=None,
            edge_distance_m=edge_distance_m,
            inside=inside,
            reason='The device did not report a GPS accuracy.',
            boundary_source=campus.boundary_source,
            captured_at=captured_at,
        )

    if accuracy_m > max_reliable_accuracy_m:
        return GpsResult(
            status=INCONCLUSIVE,
            distance_m=distance_m,
            accuracy_m=accuracy_m,
            edge_distance_m=edge_distance_m,
            inside=inside,
            reason=(
                f'GPS accuracy of {accuracy_m:.0f} m is too coarse to be reliable '
                f'(limit {max_reliable_accuracy_m:.0f} m).'
            ),
            boundary_source=campus.boundary_source,
            captured_at=captured_at,
        )

    if accuracy_m >= edge_distance_m:
        # The error circle covers the campus edge, so the reading cannot settle
        # the question either way.
        return GpsResult(
            status=INCONCLUSIVE,
            distance_m=distance_m,
            accuracy_m=accuracy_m,
            edge_distance_m=edge_distance_m,
            inside=inside,
            reason=(
                f'The reported accuracy ({accuracy_m:.0f} m) is wider than the '
                f'distance to the campus boundary ({edge_distance_m:.0f} m).'
            ),
            boundary_source=campus.boundary_source,
            captured_at=captured_at,
        )

    status = LOCATION_MATCH if inside else LOCATION_MISMATCH
    return GpsResult(
        status=status,
        distance_m=distance_m,
        accuracy_m=accuracy_m,
        edge_distance_m=edge_distance_m,
        inside=inside,
        reason='',
        boundary_source=campus.boundary_source,
        captured_at=captured_at,
    )


def mask_coordinate(value: float | None, precision: int = 3) -> float | None:
    """Reduce a coordinate's precision for display to non-owners.

    Three decimal places is roughly a 100 m cell, which is enough to show
    "near the campus" without publishing an exact position.
    """
    if value is None:
        return None
    return round(float(value), precision)