"""Geolocation cross-matching model.

This module contains a small, dependency-free machine learning model that
compares two geolocations:

* a constant reference point (the college campus, from configuration), and
* a candidate point captured from a device GPS or a simulated random shot.

The model is a multinomial-free binary logistic regression trained at runtime
on deterministically generated labelled samples (points inside the campus
radius versus points scattered across the surrounding region). Training is
reproducible (fixed seed) so every deployment behaves identically, and the
learned weights are cached on disk so the cost is paid only once.

No third-party ML dependency is required, which keeps the desktop build and
the serverless deployment light and offline friendly.
"""

from __future__ import annotations

import json
import math
import os
import random
import tempfile
from dataclasses import dataclass, field
from typing import Iterable, Sequence

EARTH_RADIUS_M = 6_371_008.8
MODEL_VERSION = 'geo-crossmatch-1.0.0'
CACHE_FILENAME = 'geo_match_model.json'

# Fixed seed keeps the trained weights reproducible across machines and runs.
TRAINING_SEED = 20240917
TRAIN_SAMPLES = 1200
VALIDATION_SAMPLES = 600
TRAIN_EPOCHS = 200
LEARNING_RATE = 0.5
L2_REGULARISATION = 0.0001

FEATURE_NAMES = (
    'log_distance_ratio',
    'sqrt_distance_ratio',
    'north_south_over_radius',
    'east_west_over_radius',
    'log_distance_over_accuracy',
    'normalised_accuracy',
)


@dataclass(frozen=True)
class GeoPoint:
    """A geolocation sample."""

    latitude: float
    longitude: float
    accuracy_m: float | None = None

    def as_dict(self) -> dict:
        return {
            'latitude': round(self.latitude, 7),
            'longitude': round(self.longitude, 7),
            'accuracy_m': round(self.accuracy_m, 1) if self.accuracy_m is not None else None,
        }


@dataclass
class GeoMatchResult:
    """Outcome of cross-matching a candidate point against the campus."""

    verdict: str
    probability: float
    distance_m: float
    accuracy_m: float | None
    campus_name: str
    campus_latitude: float
    campus_longitude: float
    campus_radius_m: float
    model_version: str = MODEL_VERSION
    model_accuracy: float | None = None

    @property
    def matched(self) -> bool:
        return self.verdict == 'match'

    def as_dict(self) -> dict:
        return {
            'verdict': self.verdict,
            'matched': self.matched,
            'probability': round(self.probability, 4),
            'distance_m': round(self.distance_m, 1),
            'accuracy_m': round(self.accuracy_m, 1) if self.accuracy_m is not None else None,
            'campus_name': self.campus_name,
            'campus_latitude': self.campus_latitude,
            'campus_longitude': self.campus_longitude,
            'campus_radius_m': self.campus_radius_m,
            'model_version': self.model_version,
            'model_accuracy': (
                round(self.model_accuracy, 4) if self.model_accuracy is not None else None
            ),
        }


@dataclass
class GeoMatchModel:
    """Trained logistic-regression cross-match model."""

    weights: Sequence[float]
    bias: float
    mean: Sequence[float]
    scale: Sequence[float]
    reference: GeoPoint
    radius_m: float
    campus_name: str
    model_version: str = MODEL_VERSION
    accuracy: float = 0.0
    decision_radius_m: float = 0.0
    training_samples: int = 0
    feature_names: Sequence[str] = field(default_factory=lambda: FEATURE_NAMES)

    # -- feature engineering -------------------------------------------------
    def features(self, candidate: GeoPoint) -> list[float]:
        return _feature_vector(self.reference, candidate, self.radius_m)

    def _standardise(self, vector: Sequence[float]) -> list[float]:
        return [
            (value - mean) / scale
            for value, mean, scale in zip(vector, self.mean, self.scale)
        ]

    def probability(self, candidate: GeoPoint) -> float:
        vector = self._standardise(self.features(candidate))
        logit = self.bias + sum(w * x for w, x in zip(self.weights, vector))
        return _sigmoid(logit)

    def match(self, candidate: GeoPoint, threshold: float = 0.5) -> GeoMatchResult:
        probability = self.probability(candidate)
        distance_m = haversine_m(
            self.reference.latitude,
            self.reference.longitude,
            candidate.latitude,
            candidate.longitude,
        )
        return GeoMatchResult(
            verdict='match' if probability >= threshold else 'mismatch',
            probability=probability,
            distance_m=distance_m,
            accuracy_m=candidate.accuracy_m,
            campus_name=self.campus_name,
            campus_latitude=self.reference.latitude,
            campus_longitude=self.reference.longitude,
            campus_radius_m=self.radius_m,
            model_version=self.model_version,
            model_accuracy=self.accuracy,
        )

    # -- (de)serialisation ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            'model_version': self.model_version,
            'campus_name': self.campus_name,
            'reference': self.reference.as_dict(),
            'radius_m': self.radius_m,
            'weights': list(self.weights),
            'bias': self.bias,
            'mean': list(self.mean),
            'scale': list(self.scale),
            'accuracy': self.accuracy,
            'decision_radius_m': self.decision_radius_m,
            'training_samples': self.training_samples,
            'feature_names': list(self.feature_names),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> 'GeoMatchModel':
        reference = payload['reference']
        return cls(
            weights=payload['weights'],
            bias=payload['bias'],
            mean=payload['mean'],
            scale=payload['scale'],
            reference=GeoPoint(
                latitude=reference['latitude'],
                longitude=reference['longitude'],
                accuracy_m=reference.get('accuracy_m'),
            ),
            radius_m=payload['radius_m'],
            campus_name=payload.get('campus_name', 'Campus'),
            model_version=payload.get('model_version', MODEL_VERSION),
            accuracy=payload.get('accuracy', 0.0),
            decision_radius_m=payload.get('decision_radius_m', 0.0),
            training_samples=payload.get('training_samples', 0),
            feature_names=payload.get('feature_names', list(FEATURE_NAMES)),
        )

    def decision_radius(self, accuracy_m: float = 20.0, threshold: float = 0.5) -> float:
        """Distance from the campus at which the model flips its verdict.

        Reported so the learned decision surface is visible instead of hidden.
        """
        low, high = 0.0, max(self.radius_m * 200.0, 1000.0)
        for _ in range(40):
            middle = (low + high) / 2.0
            point = _offset_point(self.reference, middle, 0.0)
            candidate = GeoPoint(point.latitude, point.longitude, accuracy_m)
            if self.probability(candidate) >= threshold:
                low = middle
            else:
                high = middle
        return low


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in metres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _offset_point(origin: GeoPoint, distance_m: float, bearing_deg: float) -> GeoPoint:
    """Move from ``origin`` by ``distance_m`` along ``bearing_deg``."""
    bearing = math.radians(bearing_deg)
    delta_lat = (distance_m * math.cos(bearing)) / EARTH_RADIUS_M
    cos_lat = math.cos(math.radians(origin.latitude)) or 1e-6
    delta_lon = (distance_m * math.sin(bearing)) / (EARTH_RADIUS_M * cos_lat)
    return GeoPoint(
        latitude=max(-90.0, min(90.0, origin.latitude + math.degrees(delta_lat))),
        longitude=max(-180.0, min(180.0, origin.longitude + math.degrees(delta_lon))),
    )


def _feature_vector(reference: GeoPoint, candidate: GeoPoint, radius_m: float) -> list[float]:
    """Build the numeric feature vector from the pair of geolocations.

    The features are scaled by the campus radius so the decision surface is
    learned at the scale that matters (tens to hundreds of metres) instead of
    being dominated by candidates that are thousands of kilometres away.
    """
    distance_m = haversine_m(
        reference.latitude, reference.longitude, candidate.latitude, candidate.longitude
    )
    radius_km = max(radius_m, 1.0) / 1000.0
    distance_ratio = (distance_m / 1000.0) / radius_km
    accuracy = candidate.accuracy_m if candidate.accuracy_m is not None else 25.0
    accuracy = max(1.0, min(float(accuracy), 500.0))

    d_lat = math.radians(candidate.latitude - reference.latitude)
    north_south_km = d_lat * EARTH_RADIUS_M / 1000.0
    cos_lat = math.cos(math.radians(reference.latitude)) or 1e-6
    east_west_km = (
        math.radians(candidate.longitude - reference.longitude)
        * EARTH_RADIUS_M
        * cos_lat
        / 1000.0
    )

    return [
        math.log1p(distance_ratio),
        math.sqrt(distance_ratio),
        north_south_km / radius_km,
        east_west_km / radius_km,
        math.log1p(distance_m / accuracy),
        min(accuracy, 200.0) / 200.0,
    ]


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def _gps_sample(origin: GeoPoint, distance_m: float, rng: random.Random) -> GeoPoint:
    """Simulate a device GPS reading ``distance_m`` away from ``origin``.

    The same reading error model is used for every sample, so the model has to
    learn the location itself rather than an artefact of the simulation.
    """
    point = _offset_point(origin, distance_m, rng.uniform(0.0, 360.0))
    accuracy = max(3.0, rng.gauss(20.0, 15.0))
    return GeoPoint(latitude=point.latitude, longitude=point.longitude, accuracy_m=accuracy)


def _negative_distance(radius_m: float, rng: random.Random) -> float:
    """Sample a distance outside the campus, dense near the boundary."""
    draw = rng.random()
    if draw < 0.60:
        return radius_m * rng.uniform(1.05, 2.5)
    if draw < 0.85:
        return radius_m * rng.uniform(2.5, 10.0)
    return radius_m * rng.uniform(10.0, 80.0)


def _training_set(
    reference: GeoPoint, radius_m: float, rng: random.Random
) -> tuple[list[list[float]], list[int]]:
    """Generate labelled samples: inside the campus radius versus outside."""
    vectors: list[list[float]] = []
    labels: list[int] = []

    # Positives: points spread uniformly over the campus disc.
    for _ in range(TRAIN_SAMPLES):
        distance = radius_m * math.sqrt(rng.random())
        vectors.append(_feature_vector(reference, _gps_sample(reference, distance, rng), radius_m))
        labels.append(1)

    # Negatives: mostly just outside the radius, so the boundary stays sharp.
    for _ in range(TRAIN_SAMPLES):
        distance = _negative_distance(radius_m, rng)
        vectors.append(_feature_vector(reference, _gps_sample(reference, distance, rng), radius_m))
        labels.append(0)

    order = list(range(len(vectors)))
    rng.shuffle(order)
    return [vectors[i] for i in order], [labels[i] for i in order]


def _validation_set(
    reference: GeoPoint, radius_m: float, rng: random.Random
) -> tuple[list[list[float]], list[int]]:
    vectors: list[list[float]] = []
    labels: list[int] = []
    for _ in range(VALIDATION_SAMPLES):
        inside = rng.random() < 0.5
        if inside:
            distance = radius_m * math.sqrt(rng.random())
            label = 1
        else:
            distance = _negative_distance(radius_m, rng)
            label = 0
        vectors.append(_feature_vector(reference, _gps_sample(reference, distance, rng), radius_m))
        labels.append(label)
    return vectors, labels


def _standardisation(vectors: Sequence[Sequence[float]]) -> tuple[list[float], list[float]]:
    count = len(vectors)
    width = len(vectors[0])
    means = [sum(row[i] for row in vectors) / count for i in range(width)]
    scales = []
    for i in range(width):
        variance = sum((row[i] - means[i]) ** 2 for row in vectors) / count
        scales.append(math.sqrt(variance) or 1.0)
    return means, scales


def _fit_logistic_regression(
    vectors: Sequence[Sequence[float]],
    labels: Sequence[int],
    means: Sequence[float],
    scales: Sequence[float],
) -> tuple[list[float], float]:
    width = len(vectors[0])
    standardised = [
        [(value - mean) / scale for value, mean, scale in zip(row, means, scales)]
        for row in vectors
    ]
    weights = [0.0] * width
    bias = 0.0
    count = len(standardised)

    for _ in range(TRAIN_EPOCHS):
        gradients = [0.0] * width
        bias_gradient = 0.0
        for row, label in zip(standardised, labels):
            logit = bias + sum(w * x for w, x in zip(weights, row))
            error = _sigmoid(logit) - label
            for i, x in enumerate(row):
                gradients[i] += error * x
            bias_gradient += error
        for i in range(width):
            weights[i] -= LEARNING_RATE * (
                gradients[i] / count + L2_REGULARISATION * weights[i]
            )
        bias -= LEARNING_RATE * (bias_gradient / count)

    return weights, bias


def train_model(
    reference: GeoPoint,
    radius_m: float,
    campus_name: str = 'Campus',
    seed: int = TRAINING_SEED,
) -> GeoMatchModel:
    """Train the cross-match model from deterministic synthetic samples."""
    rng = random.Random(seed)
    vectors, labels = _training_set(reference, radius_m, rng)
    means, scales = _standardisation(vectors)
    weights, bias = _fit_logistic_regression(vectors, labels, means, scales)

    model = GeoMatchModel(
        weights=weights,
        bias=bias,
        mean=means,
        scale=scales,
        reference=reference,
        radius_m=radius_m,
        campus_name=campus_name,
        accuracy=0.0,
        training_samples=len(vectors),
    )

    validation_rng = random.Random(seed + 1)
    validation_vectors, validation_labels = _validation_set(reference, radius_m, validation_rng)
    correct = 0
    for vector, label in zip(validation_vectors, validation_labels):
        standardised = [
            (value - mean) / scale for value, mean, scale in zip(vector, means, scales)
        ]
        probability = _sigmoid(bias + sum(w * x for w, x in zip(weights, standardised)))
        if (probability >= 0.5) == bool(label):
            correct += 1
    model.accuracy = correct / len(validation_vectors) if validation_vectors else 0.0
    model.decision_radius_m = model.decision_radius()
    return model


# ---------------------------------------------------------------------------
# Cached access
# ---------------------------------------------------------------------------
_MODEL_CACHE: dict[tuple, GeoMatchModel] = {}


def _cache_path(folder: str) -> str:
    return os.path.join(folder, CACHE_FILENAME)


def _load_cached_model(folder: str, key: tuple) -> GeoMatchModel | None:
    path = _cache_path(folder)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None

    reference = payload.get('reference', {})
    cached_key = (
        payload.get('model_version'),
        reference.get('latitude'),
        reference.get('longitude'),
        payload.get('radius_m'),
        payload.get('campus_name'),
    )
    if cached_key != key:
        return None

    try:
        return GeoMatchModel.from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return None


def _store_model(folder: str, model: GeoMatchModel) -> None:
    try:
        os.makedirs(folder, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            'w', encoding='utf-8', dir=folder, delete=False, suffix='.tmp'
        )
        with handle:
            json.dump(model.to_dict(), handle)
        os.replace(handle.name, _cache_path(folder))
    except OSError:
        # A read-only filesystem is acceptable; the model simply retrains next time.
        pass


def get_model(
    reference: GeoPoint,
    radius_m: float,
    campus_name: str = 'Campus',
    folder: str | None = None,
    force_retrain: bool = False,
) -> GeoMatchModel:
    """Return the trained model, using an on-disk cache when available."""
    key = (MODEL_VERSION, reference.latitude, reference.longitude, radius_m, campus_name)
    if not force_retrain and key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    model: GeoMatchModel | None = None
    if folder and not force_retrain:
        model = _load_cached_model(folder, key)

    if model is None:
        model = train_model(reference, radius_m, campus_name)
        if folder:
            _store_model(folder, model)

    _MODEL_CACHE[key] = model
    return model


def random_shot(
    reference: GeoPoint,
    radius_m: float,
    rng: random.Random | None = None,
    inside_ratio: float = 0.5,
) -> GeoPoint:
    """Produce a random geolocation with its own reported accuracy.

    Used by the "random shot" control so the cross-match can be exercised with
    random points (both inside and outside the campus) without a device GPS.
    The simulated ground truth is only used for display; the verdict always
    comes from the trained model.
    """
    rng = rng or random.Random()
    bearing = rng.uniform(0.0, 360.0)
    if rng.random() < inside_ratio:
        distance = radius_m * math.sqrt(rng.random())
    else:
        distance = radius_m * rng.uniform(1.05, 40.0)
    accuracy = max(3.0, rng.gauss(20.0, 15.0))
    point = _offset_point(reference, distance, bearing)
    return GeoPoint(latitude=point.latitude, longitude=point.longitude, accuracy_m=accuracy)
