"""Decision logic that combines GPS and image evidence.

This module is intentionally free of Flask and database imports so the
decision rules can be unit tested on their own.

Governing principles
--------------------
* The two signals stay separate. Neither one is a proof of physical presence.
* No combination of uncertain signals produces an automatic rejection.
  A student is never penalised solely because of a low similarity score or an
  inaccurate GPS reading; such cases go to a human reviewer.
* Missing evidence is recorded as missing evidence, not as misconduct.
* Contradictory evidence is flagged rather than resolved silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.campus import (
    INCONCLUSIVE as GPS_INCONCLUSIVE,
    LOCATION_MATCH,
    LOCATION_MISMATCH,
    MISSING as GPS_MISSING,
    GpsResult,
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

# Advisory outcomes. Neither of these is an automated accept or reject.
SUGGESTED_CAMPUS_MATCH = 'SUGGESTED_CAMPUS_MATCH'
FACULTY_REVIEW = 'FACULTY_REVIEW'

FLAG_GPS_MATCH_IMAGE_LOW = 'gps_match_but_image_low_similarity'
FLAG_GPS_MISMATCH_IMAGE_MATCH = 'image_match_but_gps_mismatch'
FLAG_GPS_INCONCLUSIVE = 'gps_inconclusive'
FLAG_GPS_MISSING = 'gps_missing'
FLAG_IMAGE_UNAVAILABLE = 'image_reference_unavailable'
FLAG_IMAGE_MISSING = 'image_missing'
FLAG_IMAGE_INVALID = 'image_invalid'
FLAG_MODEL_UNAVAILABLE = 'image_model_unavailable'
FLAG_NO_CONTRADICTION = ''


@dataclass
class VerificationDecision:
    """Structured outcome combining both signals."""

    final_decision: str
    gps: GpsResult
    image: ImageVerificationResult
    flags: list[str] = field(default_factory=list)
    rationale: str = ''
    requires_human_review: bool = True

    def as_dict(self) -> dict:
        return {
            'gps_verification': self.gps.as_dict(),
            'image_verification': self.image.as_dict(),
            'final_decision': self.final_decision,
            'flags': list(self.flags),
            'rationale': self.rationale,
            'requires_human_review': self.requires_human_review,
        }

    @property
    def flag_text(self) -> str:
        return ','.join(flag for flag in self.flags if flag)


@dataclass(frozen=True)
class DecisionPolicy:
    """Thresholds governing the combination step."""

    max_reliable_accuracy_m: float = 100.0
    similarity_threshold: float = 0.92


def decide(
    gps: GpsResult,
    image: ImageVerificationResult,
    policy: DecisionPolicy | None = None,
) -> VerificationDecision:
    """Combine GPS and image evidence into a reviewable outcome."""
    policy = policy or DecisionPolicy()
    flags: list[str] = []
    reasons: list[str] = []

    # --- GPS evidence ----------------------------------------------------
    gps_status = gps.status
    if gps_status == GPS_MISSING:
        flags.append(FLAG_GPS_MISSING)
        reasons.append(gps.reason or 'No location was provided.')
    elif gps_status == GPS_INCONCLUSIVE:
        flags.append(FLAG_GPS_INCONCLUSIVE)
        reasons.append(gps.reason or 'The location reading was not reliable enough.')
    elif gps_status == LOCATION_MISMATCH:
        reasons.append(
            f'Reported location is {gps.distance_m:.0f} m from the campus boundary.'
            if gps.distance_m is not None
            else 'Reported location is outside the campus area.'
        )

    # --- image evidence --------------------------------------------------
    image_status = image.status
    if image_status == POSSIBLE_VISUAL_MATCH:
        pass
    elif image_status == LOW_VISUAL_SIMILARITY:
        pass
    elif image_status == REFERENCE_IMAGES_UNAVAILABLE:
        flags.append(FLAG_IMAGE_UNAVAILABLE)
        reasons.append(image.reason or 'No campus reference images are configured.')
    elif image_status == MODEL_UNAVAILABLE:
        flags.append(FLAG_MODEL_UNAVAILABLE)
        reasons.append(image.reason or 'The image comparison backend is unavailable.')
    elif image_status == INVALID_IMAGE:
        flags.append(FLAG_IMAGE_INVALID)
        reasons.append(image.reason or 'The submitted image could not be read.')
    else:  # INCONCLUSIVE, which includes "no photo submitted"
        flags.append(FLAG_IMAGE_MISSING)
        reasons.append(image.reason or 'No usable photo was submitted.')

    # --- contradictions --------------------------------------------------
    if gps_status == LOCATION_MATCH and image_status == LOW_VISUAL_SIMILARITY:
        flags.append(FLAG_GPS_MATCH_IMAGE_LOW)
        reasons.append(
            'The student reports being on campus but the photo looks unlike the '
            'campus reference images.'
        )
    if gps_status == LOCATION_MISMATCH and image_status == POSSIBLE_VISUAL_MATCH:
        flags.append(FLAG_GPS_MISMATCH_IMAGE_MATCH)
        reasons.append(
            'The photo resembles a campus reference image but the reported '
            'location is away from campus.'
        )

    unresolved = [flag for flag in flags if flag]
    if unresolved:
        # Any unresolved signal means a person should look at the evidence.
        final = FACULTY_REVIEW
        requires_review = True
    elif (
        gps_status == LOCATION_MATCH
        and image_status == POSSIBLE_VISUAL_MATCH
    ):
        final = SUGGESTED_CAMPUS_MATCH
        requires_review = True  # advisory only; still recorded as a suggestion
        reasons.append(
            'Reported location is on campus and the photo resembles a campus '
            'reference image. This remains a suggestion for a reviewer, not proof.'
        )
    else:
        final = FACULTY_REVIEW
        requires_review = True
        reasons.append('The available evidence does not point to a clear outcome.')

    return VerificationDecision(
        final_decision=final,
        gps=gps,
        image=image,
        flags=unresolved,
        rationale=' '.join(reason for reason in reasons if reason),
        requires_human_review=requires_review,
    )