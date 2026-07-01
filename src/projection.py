"""
Projection Engine: maps the internal CanonicalCandidate (full evidence,
provenance, every field) into a consumer-facing CandidateProjection
(flat, no evidence trail, just values + confidence). Also performs a
final lightweight schema validation pass on the projection before it's
allowed to be emitted.

Keeping this as a separate stage (rather than emitting CanonicalCandidate
directly) is what makes the output schema independently versionable --
adding an "ats_export" or "public_profile" projection later is a new
function here, with zero changes to merge/confidence/provenance.
"""
from __future__ import annotations

from typing import List

from src.models import CanonicalCandidate, CandidateProjection, SCHEMA_VERSION


def project(canonical: CanonicalCandidate) -> CandidateProjection:
    def val(name):
        fv = canonical.get(name)
        return fv.value if fv else None

    field_confidence = {name: round(fv.confidence, 4) for name, fv in canonical.fields.items()}
    overall = round(sum(field_confidence.values()) / len(field_confidence), 4) if field_confidence else 0.0

    return CandidateProjection(
        candidate_id=canonical.identity_resolution.get("candidate_id", "unresolved"),
        full_name=val("full_name"),
        email=val("email"),
        phone=val("phone"),
        location=val("location"),
        current_title=val("current_title"),
        current_company=val("current_company"),
        years_experience=val("years_experience"),
        skills=val("skills") or [],
        education=val("education") or [],
        github_username=val("github_username"),
        overall_confidence=overall,
        field_confidence=field_confidence,
    )


def validate_projection_schema(projection: CandidateProjection) -> List[str]:
    """
    Lightweight structural schema validation of the OUTPUT (not the same
    as field-level validation.py, which validates raw values during
    merge). Ensures the emitted JSON always has the shape downstream
    consumers expect.
    """
    errors = []
    if not projection.candidate_id:
        errors.append("candidate_id is required in output schema")
    if not isinstance(projection.skills, list):
        errors.append("skills must be a list")
    if not isinstance(projection.education, list):
        errors.append("education must be a list")
    if not (0.0 <= projection.overall_confidence <= 1.0):
        errors.append("overall_confidence out of [0,1] range")
    for fname, conf in projection.field_confidence.items():
        if not (0.0 <= conf <= 1.0):
            errors.append(f"field_confidence[{fname}] out of [0,1] range")
    return errors


PROJECTION_SCHEMA_VERSION = SCHEMA_VERSION
