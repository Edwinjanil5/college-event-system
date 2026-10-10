"""Tests for the geolocation cross-match model."""

import math
import random

from app.geo_matching import (
    FEATURE_NAMES,
    GeoMatchModel,
    GeoPoint,
    get_model,
    haversine_m,
    random_shot,
    train_model,
)


CAMPUS = GeoPoint(latitude=9.1553906, longitude=76.7310322)
RADIUS_M = 250.0


_CACHED_MODEL = None


def _model():
    """Train once per test session; training is deliberately slow-ish."""
    global _CACHED_MODEL
    if _CACHED_MODEL is None:
        _CACHED_MODEL = train_model(CAMPUS, RADIUS_M, 'College of Applied Science, Adoor')
    return _CACHED_MODEL


def _offset(distance_m, bearing_deg, accuracy_m=20.0):
    from app.geo_matching import _offset_point

    point = _offset_point(CAMPUS, distance_m, bearing_deg)
    return GeoPoint(point.latitude, point.longitude, accuracy_m)


def test_haversine_matches_known_distance():
    # One degree of latitude is roughly 111 km anywhere on the globe.
    assert math.isclose(haversine_m(9.0, 76.0, 10.0, 76.0), 111_195.0, rel_tol=0.01)
    assert haversine_m(9.1553906, 76.7310322, 9.1553906, 76.7310322) == 0.0


def test_model_trains_reproducibly_and_is_accurate():
    first = _model()
    second = train_model(CAMPUS, RADIUS_M, 'College of Applied Science, Adoor')
    assert first.weights == second.weights, 'training must be deterministic'
    assert first.accuracy >= 0.90, f'validation accuracy too low: {first.accuracy}'
    assert first.training_samples == 2400
    assert list(first.feature_names) == list(FEATURE_NAMES)


def test_model_matches_inside_campus_and_rejects_far_away_places():
    model = _model()

    at_campus = model.match(GeoPoint(CAMPUS.latitude, CAMPUS.longitude, 15.0))
    assert at_campus.verdict == 'match'
    assert at_campus.matched is True
    assert at_campus.distance_m < 5
    assert at_campus.probability > 0.9

    nearby = model.match(_offset(120.0, 42.0))
    assert nearby.verdict == 'match'

    # A different campus entirely must never be treated as a match.
    trivandrum = GeoPoint(8.5241, 76.9366, 30.0)
    assert model.match(trivandrum).verdict == 'mismatch'

    kochi = GeoPoint(9.9312, 76.2673, 30.0)
    assert model.match(kochi).verdict == 'mismatch'


def test_learned_boundary_is_near_the_campus_radius():
    model = _model()
    boundary = model.decision_radius()
    assert 50.0 < boundary < 1500.0, f'unreasonable decision boundary: {boundary}'

    inside = model.match(_offset(boundary * 0.6, 0.0))
    outside = model.match(_offset(boundary * 3.0, 0.0))
    assert inside.verdict == 'match'
    assert outside.verdict == 'mismatch'


def test_random_shots_are_valid_and_cover_both_verdicts():
    model = _model()
    rng = random.Random(11)
    verdicts = set()
    for _ in range(60):
        point = random_shot(CAMPUS, RADIUS_M, rng)
        assert -90.0 <= point.latitude <= 90.0
        assert -180.0 <= point.longitude <= 180.0
        assert point.accuracy_m and point.accuracy_m > 0
        verdicts.add(model.match(point).verdict)
    assert verdicts == {'match', 'mismatch'}


def test_model_cache_round_trip(tmp_path):
    folder = str(tmp_path / 'model-cache')
    first = get_model(CAMPUS, RADIUS_M, 'College of Applied Science, Adoor', folder=folder)
    assert (tmp_path / 'model-cache' / 'geo_match_model.json').is_file()

    cached = get_model(CAMPUS, RADIUS_M, 'College of Applied Science, Adoor', folder=folder)
    assert cached.weights == first.weights

    # A different reference location must not reuse the cached weights.
    other = get_model(GeoPoint(9.0, 76.0), RADIUS_M, 'Other campus', folder=folder)
    assert other.weights != first.weights
    assert other.reference.latitude == 9.0


def test_model_serialisation_preserves_predictions():
    model = _model()
    restored = GeoMatchModel.from_dict(model.to_dict())
    point = _offset(80.0, 200.0)
    assert restored.match(point).verdict == model.match(point).verdict
    assert restored.accuracy == model.accuracy
