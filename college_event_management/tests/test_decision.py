"""Tests for the combined decision logic (pure, no Flask involved)."""

import pytest

from app.campus import GpsResult, INCONCLUSIVE, LOCATION_MATCH, LOCATION_MISMATCH, MISSING
from app.decision import (
    FACULTY_REVIEW,
    FLAG_GPS_INCONCLUSIVE,
    FLAG_GPS_MATCH_IMAGE_LOW,
    FLAG_GPS_MISMATCH_IMAGE_MATCH,
    FLAG_GPS_MISSING,
    FLAG_IMAGE_INVALID,
    FLAG_IMAGE_MISSING,
    FLAG_IMAGE_UNAVAILABLE,
    FLAG_MODEL_UNAVAILABLE,
    SUGGESTED_CAMPUS_MATCH,
    decide,
)
from app.image_verification import (
    INCONCLUSIVE as IMAGE_INCONCLUSIVE,
    INVALID_IMAGE,
    LOW_VISUAL_SIMILARITY,
    MODEL_UNAVAILABLE,
    POSSIBLE_VISUAL_MATCH,
    REFERENCE_IMAGES_UNAVAILABLE,
    ImageVerificationResult,
)


def gps(status, distance=35.0, accuracy=12.0, reason=''):
    return GpsResult(
        status=status,
        distance_m=distance,
        accuracy_m=accuracy,
        edge_distance_m=distance,
        inside=status == LOCATION_MATCH,
        reason=reason,
    )


def image(status, similarity=0.87, reference='academic-block.jpg'):
    return ImageVerificationResult(
        status=status,
        similarity=similarity,
        best_reference=reference if status == POSSIBLE_VISUAL_MATCH else None,
        backend='perceptual',
        reference_count=3,
    )


# ---------------------------------------------------------------------------
def test_gps_match_and_visual_match_suggests_a_campus_match():
    outcome = decide(gps(LOCATION_MATCH), image(POSSIBLE_VISUAL_MATCH))
    assert outcome.final_decision == SUGGESTED_CAMPUS_MATCH
    assert outcome.flags == []
    assert outcome.requires_human_review is True, 'a suggestion is never an automatic pass'
    assert 'not proof' in outcome.rationale.lower() or 'suggestion' in outcome.rationale.lower()


def test_gps_match_with_low_similarity_goes_to_review_with_a_contradiction_flag():
    outcome = decide(gps(LOCATION_MATCH), image(LOW_VISUAL_SIMILARITY, similarity=0.4))
    assert outcome.final_decision == FACULTY_REVIEW
    assert FLAG_GPS_MATCH_IMAGE_LOW in outcome.flags


def test_gps_mismatch_with_visual_match_is_flagged_as_contradictory():
    outcome = decide(gps(LOCATION_MISMATCH, distance=5000.0), image(POSSIBLE_VISUAL_MATCH))
    assert outcome.final_decision == FACULTY_REVIEW
    assert FLAG_GPS_MISMATCH_IMAGE_MATCH in outcome.flags


def test_gps_mismatch_with_low_similarity_is_never_an_automatic_rejection():
    outcome = decide(gps(LOCATION_MISMATCH, distance=5000.0), image(LOW_VISUAL_SIMILARITY, 0.2))
    assert outcome.final_decision == FACULTY_REVIEW
    assert outcome.requires_human_review is True


def test_poor_gps_accuracy_is_inconclusive_and_reviewed():
    outcome = decide(
        gps(INCONCLUSIVE, accuracy=800.0, reason='GPS accuracy of 800 m is too coarse'),
        image(POSSIBLE_VISUAL_MATCH),
    )
    assert outcome.final_decision == FACULTY_REVIEW
    assert FLAG_GPS_INCONCLUSIVE in outcome.flags


def test_missing_gps_is_recorded_as_missing_not_misconduct():
    outcome = decide(gps(MISSING, distance=None, reason='Location permission denied'), image(POSSIBLE_VISUAL_MATCH))
    assert FLAG_GPS_MISSING in outcome.flags
    assert outcome.final_decision == FACULTY_REVIEW


def test_missing_reference_images_are_handled():
    outcome = decide(gps(LOCATION_MATCH), image(REFERENCE_IMAGES_UNAVAILABLE))
    assert FLAG_IMAGE_UNAVAILABLE in outcome.flags
    assert outcome.final_decision == FACULTY_REVIEW


def test_unavailable_model_is_handled():
    outcome = decide(gps(LOCATION_MATCH), image(MODEL_UNAVAILABLE))
    assert FLAG_MODEL_UNAVAILABLE in outcome.flags
    assert outcome.final_decision == FACULTY_REVIEW


def test_invalid_image_is_handled():
    outcome = decide(gps(LOCATION_MATCH), image(INVALID_IMAGE))
    assert FLAG_IMAGE_INVALID in outcome.flags


def test_absent_photo_is_handled():
    outcome = decide(gps(LOCATION_MATCH), image(IMAGE_INCONCLUSIVE))
    assert FLAG_IMAGE_MISSING in outcome.flags


@pytest.mark.parametrize(
    'gps_status,image_status',
    [
        (LOCATION_MATCH, POSSIBLE_VISUAL_MATCH),
        (LOCATION_MATCH, LOW_VISUAL_SIMILARITY),
        (LOCATION_MISMATCH, POSSIBLE_VISUAL_MATCH),
        (LOCATION_MISMATCH, LOW_VISUAL_SIMILARITY),
        (INCONCLUSIVE, POSSIBLE_VISUAL_MATCH),
        (MISSING, LOW_VISUAL_SIMILARITY),
    ],
)
def test_every_combination_requires_a_human(gps_status, image_status):
    outcome = decide(gps(gps_status), image(image_status))
    assert outcome.requires_human_review is True
    assert outcome.final_decision in {SUGGESTED_CAMPUS_MATCH, FACULTY_REVIEW}


def test_serialised_payload_matches_the_documented_shape():
    outcome = decide(gps(LOCATION_MATCH, distance=35.2, accuracy=12.0), image(POSSIBLE_VISUAL_MATCH, 0.87))
    payload = outcome.as_dict()
    assert set(payload) >= {
        'gps_verification',
        'image_verification',
        'final_decision',
        'flags',
        'rationale',
        'requires_human_review',
    }
    assert payload['gps_verification']['status'] == 'LOCATION_MATCH'
    assert payload['gps_verification']['distance_meters'] == pytest.approx(35.2)
    assert payload['gps_verification']['accuracy_meters'] == pytest.approx(12.0)
    assert payload['image_verification']['status'] == 'POSSIBLE_VISUAL_MATCH'
    assert payload['image_verification']['best_reference'] == 'academic-block.jpg'
    assert payload['image_verification']['similarity'] == pytest.approx(0.87)
    assert payload['final_decision'] == 'SUGGESTED_CAMPUS_MATCH'


def test_flag_text_is_stored_as_a_comma_separated_string():
    # Missing GPS and no photo raise two independent flags.
    outcome = decide(
        gps(MISSING, distance=None, reason='Location permission denied'),
        image(IMAGE_INCONCLUSIVE),
    )
    stored = outcome.flag_text
    assert FLAG_GPS_MISSING in stored
    assert FLAG_IMAGE_MISSING in stored
    assert ',' in stored


def test_single_flag_has_no_separator():
    outcome = decide(gps(LOCATION_MATCH), image(LOW_VISUAL_SIMILARITY, 0.3))
    assert outcome.flag_text == FLAG_GPS_MATCH_IMAGE_LOW