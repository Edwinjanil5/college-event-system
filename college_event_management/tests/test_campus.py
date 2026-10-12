"""Tests for campus boundary maths and GPS outcome classification."""

import json

import pytest

from app.campus import (
    INCONCLUSIVE,
    LOCATION_MATCH,
    LOCATION_MISMATCH,
    MISSING,
    CampusArea,
    GeoPoint,
    campus_from_config,
    evaluate_location,
    haversine_m,
    load_polygon,
    mask_coordinate,
    normalise_accuracy,
    point_in_polygon,
    validate_coordinate,
)

# Coordinates supplied by the college.
CAMPUS_LAT = 9.1557
CAMPUS_LNG = 76.7369


def make_campus(radius_m=250.0):
    return CampusArea(
        name='College of Applied Sciences, Adoor (IHRD)',
        address='Hospital, Link Road, Parass La, Adoor, Kerala, India - 691523',
        latitude=CAMPUS_LAT,
        longitude=CAMPUS_LNG,
        radius_m=radius_m,
    )


# ---------------------------------------------------------------------------
# Distance maths
# ---------------------------------------------------------------------------
def test_haversine_is_zero_for_identical_points():
    assert haversine_m(CAMPUS_LAT, CAMPUS_LNG, CAMPUS_LAT, CAMPUS_LNG) == 0.0


def test_haversine_matches_known_separation():
    # One degree of latitude is about 111 km.
    assert 111_000 < haversine_m(9.0, 76.0, 10.0, 76.0) < 112_000
    # Adoor to Thiruvananthapuram is about 74 km in a straight line.
    tvm = haversine_m(CAMPUS_LAT, CAMPUS_LNG, 8.5241, 76.9366)
    assert 70_000 < tvm < 80_000


# ---------------------------------------------------------------------------
# Configured reference point
# ---------------------------------------------------------------------------
def test_campus_is_built_from_configuration():
    campus = campus_from_config(
        {
            'CAMPUS_NAME': 'College of Applied Sciences, Adoor (IHRD)',
            'CAMPUS_LATITUDE': '9.1557',
            'CAMPUS_LONGITUDE': '76.7369',
            'CAMPUS_RADIUS_M': '300',
            'CAMPUS_POLYGON_FILE': '',
        }
    )
    assert campus.latitude == pytest.approx(9.1557)
    assert campus.longitude == pytest.approx(76.7369)
    assert campus.radius_m == 300.0
    assert campus.boundary_source == 'radius'


# ---------------------------------------------------------------------------
# GPS outcomes
# ---------------------------------------------------------------------------
def test_coordinates_at_the_reference_point_match():
    result = evaluate_location(
        make_campus(), CAMPUS_LAT, CAMPUS_LNG, 8, max_reliable_accuracy_m=100
    )
    assert result.status == LOCATION_MATCH
    assert result.distance_m == pytest.approx(0.0, abs=0.5)
    assert result.inside is True


def test_coordinates_inside_the_radius_match():
    # ~111 m north of the reference point, well inside a 250 m radius.
    result = evaluate_location(
        make_campus(), CAMPUS_LAT + 0.001, CAMPUS_LNG, 10, max_reliable_accuracy_m=100
    )
    assert result.status == LOCATION_MATCH
    assert 100 < result.distance_m < 130


def test_coordinates_clearly_outside_are_a_mismatch():
    result = evaluate_location(
        make_campus(), CAMPUS_LAT + 0.05, CAMPUS_LNG + 0.05, 10, max_reliable_accuracy_m=100
    )
    assert result.status == LOCATION_MISMATCH
    assert result.inside is False
    assert result.distance_m > 1000


def test_invalid_coordinates_are_missing_not_mismatch():
    for latitude, longitude in [
        (None, None),
        ('abc', 76.7),
        (91.0, 76.7),
        (9.1, 181.0),
        (float('nan'), 76.7),
        (float('inf'), 76.7),
    ]:
        result = evaluate_location(
            make_campus(), latitude, longitude, 10, max_reliable_accuracy_m=100
        )
        assert result.status == MISSING, f'{latitude},{longitude} should be MISSING'
        assert result.inside is None


def test_zero_accuracy_is_accepted_and_treated_as_precise():
    result = evaluate_location(
        make_campus(), CAMPUS_LAT, CAMPUS_LNG, 0, max_reliable_accuracy_m=100
    )
    assert result.status == LOCATION_MATCH


def test_negative_and_absurd_accuracy_are_handled():
    accuracy, error = normalise_accuracy(-5)
    assert accuracy is None and error

    accuracy, error = normalise_accuracy(99_999)
    assert accuracy is None and error

    accuracy, error = normalise_accuracy(None)
    assert accuracy is None and error is None


def test_missing_accuracy_still_classifies_but_notes_the_weakness():
    result = evaluate_location(
        make_campus(), CAMPUS_LAT, CAMPUS_LNG, None, max_reliable_accuracy_m=100
    )
    assert result.status == LOCATION_MATCH
    assert 'accuracy' in result.reason.lower()


def test_poor_accuracy_is_inconclusive_not_mismatch():
    result = evaluate_location(
        make_campus(), CAMPUS_LAT + 0.05, CAMPUS_LNG, 800, max_reliable_accuracy_m=100
    )
    assert result.status == INCONCLUSIVE
    assert 'too coarse' in result.reason


def test_accuracy_wider_than_the_boundary_gap_is_inconclusive():
    # 20 m outside the edge with 50 m accuracy (still under the 100 m
    # reliability limit): the error circle covers the boundary.
    outside = CAMPUS_LAT + (270.0 / 111_195.0)
    result = evaluate_location(
        make_campus(), outside, CAMPUS_LNG, 50, max_reliable_accuracy_m=100
    )
    assert result.status == INCONCLUSIVE
    assert 'wider than' in result.reason


def test_boundary_condition_clear_cases_and_ambiguous_edge():
    metres_per_degree = 111_195.0

    def offset(metres):
        return CAMPUS_LAT + metres / metres_per_degree

    # Comfortably inside: 100 m from the centre, so 150 m of margin to the edge.
    inside = evaluate_location(
        make_campus(), offset(100), CAMPUS_LNG, 5, max_reliable_accuracy_m=100
    )
    assert inside.status == LOCATION_MATCH

    # Comfortably outside: 800 m from the centre, 550 m beyond the edge.
    outside = evaluate_location(
        make_campus(), offset(800), CAMPUS_LNG, 5, max_reliable_accuracy_m=100
    )
    assert outside.status == LOCATION_MISMATCH

    # Exactly on the boundary: even a precise reading cannot separate
    # "inside" from "outside", so the honest answer is inconclusive.
    on_the_edge = evaluate_location(
        make_campus(), offset(250), CAMPUS_LNG, 5, max_reliable_accuracy_m=100
    )
    assert on_the_edge.status == INCONCLUSIVE
    assert on_the_edge.edge_distance_m < 5.0


def test_threshold_is_configurable_not_hardcoded():
    tight = evaluate_location(
        make_campus(radius_m=50), CAMPUS_LAT + 0.001, CAMPUS_LNG, 10, max_reliable_accuracy_m=100
    )
    wide = evaluate_location(
        make_campus(radius_m=1000), CAMPUS_LAT + 0.001, CAMPUS_LNG, 10, max_reliable_accuracy_m=100
    )
    assert tight.status == LOCATION_MISMATCH
    assert wide.status == LOCATION_MATCH


# ---------------------------------------------------------------------------
# Polygon support
# ---------------------------------------------------------------------------
def test_point_in_polygon_basics():
    square = [(9.0, 76.0), (9.0, 76.01), (9.01, 76.01), (9.01, 76.0)]
    assert point_in_polygon(9.005, 76.005, square) is True
    assert point_in_polygon(9.02, 76.005, square) is False
    assert point_in_polygon(9.005, 76.02, square) is False


def test_polygon_replaces_radius_when_loaded(tmp_path):
    polygon_file = tmp_path / 'campus.geojson'
    # A 1 km box around the reference point.
    lat_delta = 0.0045
    lng_delta = 0.0046
    payload = {
        'type': 'Feature',
        'geometry': {
            'type': 'Polygon',
            'coordinates': [
                [
                    [CAMPUS_LNG - lng_delta, CAMPUS_LAT - lat_delta],
                    [CAMPUS_LNG + lng_delta, CAMPUS_LAT - lat_delta],
                    [CAMPUS_LNG + lng_delta, CAMPUS_LAT + lat_delta],
                    [CAMPUS_LNG - lng_delta, CAMPUS_LAT + lat_delta],
                    [CAMPUS_LNG - lng_delta, CAMPUS_LAT - lat_delta],
                ]
            ],
        },
    }
    polygon_file.write_text(json.dumps(payload), encoding='utf-8')

    polygon, source = load_polygon(str(polygon_file))
    assert len(polygon) == 4  # closing vertex removed
    assert source == str(polygon_file)

    campus = CampusArea(
        name='campus',
        address='',
        latitude=CAMPUS_LAT,
        longitude=CAMPUS_LNG,
        radius_m=250.0,
        polygon=polygon,
        polygon_source=source,
    )
    assert campus.boundary_source == 'polygon'

    inside = evaluate_location(
        campus, CAMPUS_LAT + 0.003, CAMPUS_LNG, 10, max_reliable_accuracy_m=100
    )
    assert inside.status == LOCATION_MATCH
    # Outside the polygon but well inside the old 250 m radius.
    outside = evaluate_location(
        campus, CAMPUS_LAT + 0.02, CAMPUS_LNG, 10, max_reliable_accuracy_m=100
    )
    assert outside.status == LOCATION_MISMATCH


def test_malformed_polygon_falls_back_to_radius(tmp_path):
    bad = tmp_path / 'bad.geojson'
    bad.write_text('{not json', encoding='utf-8')
    polygon, source = load_polygon(str(bad))
    assert polygon == ()
    assert source == ''

    too_few = tmp_path / 'line.geojson'
    too_few.write_text(json.dumps({'geometry': {'type': 'Polygon', 'coordinates': [[[1, 2], [3, 4]]]}}), encoding='utf-8')
    polygon, _ = load_polygon(str(too_few))
    assert polygon == ()

    assert load_polygon(None) == ((), '')
    assert load_polygon('missing-file.geojson') == ((), '')


# ---------------------------------------------------------------------------
# Privacy helper
# ---------------------------------------------------------------------------
def test_masking_reduces_coordinate_precision():
    assert mask_coordinate(9.15574321) == pytest.approx(9.156)
    assert mask_coordinate(None) is None
    assert mask_coordinate(76.73691234, precision=2) == pytest.approx(76.74)