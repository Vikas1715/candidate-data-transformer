"""
Data Quality Report: summarizes missing, invalid, duplicate, and
inconsistent fields for a candidate's merged data, plus an overall
0-100 quality score. Meant to be read *before* trusting the transform
output -- e.g. a batch run can flag low-quality candidates for manual
review.

Score composition (deterministic, documented so it's auditable):
  - completeness_score: fraction of CANONICAL_FIELDS that have a value.
  - validity_score:     fraction of populated fields whose winning
                         evidence passed field-level validation.
  - consistency_score:  1 - (fraction of populated fields that are in
                         conflict across sources).
  overall = round(100 * mean(completeness, validity, consistency))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.models import CanonicalCandidate, CANONICAL_FIELDS
from src.validation import cross_field_validate


@dataclass
class DataQualityReport:
    candidate_id: str
    missing_fields: List[str] = field(default_factory=list)
    invalid_fields: List[Dict[str, Any]] = field(default_factory=list)
    conflicting_fields: List[Dict[str, Any]] = field(default_factory=list)
    cross_field_warnings: List[str] = field(default_factory=list)
    completeness_score: float = 0.0
    validity_score: float = 0.0
    consistency_score: float = 0.0
    overall_quality_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "missing_fields": self.missing_fields,
            "invalid_fields": self.invalid_fields,
            "conflicting_fields": self.conflicting_fields,
            "cross_field_warnings": self.cross_field_warnings,
            "scores": {
                "completeness": round(self.completeness_score, 4),
                "validity": round(self.validity_score, 4),
                "consistency": round(self.consistency_score, 4),
                "overall_quality_score": round(self.overall_quality_score, 2),
            },
        }


def build_quality_report(canonical: CanonicalCandidate, candidate_id: str) -> DataQualityReport:
    report = DataQualityReport(candidate_id=candidate_id)

    populated = {name: fv for name, fv in canonical.fields.items() if fv.value is not None}
    missing = [f for f in CANONICAL_FIELDS if f not in populated and f != "candidate_id"]
    report.missing_fields = missing

    for name, fv in populated.items():
        winner_ev = next((e for e in fv.evidence if e.source == fv.winning_source), None)
        if winner_ev and not winner_ev.valid:
            report.invalid_fields.append({
                "field": name, "value": fv.value, "source": fv.winning_source,
                "notes": winner_ev.validation_notes,
            })
        if fv.conflict:
            report.conflicting_fields.append({
                "field": name, "winning_value": fv.value, "winning_source": fv.winning_source,
                "conflicting_values": fv.conflicting_values,
            })

    flat_values = {name: fv.value for name, fv in populated.items()}
    report.cross_field_warnings = cross_field_validate(flat_values)

    total_fields = len([f for f in CANONICAL_FIELDS if f != "candidate_id"])
    report.completeness_score = (total_fields - len(missing)) / total_fields if total_fields else 0.0
    report.validity_score = (
        (len(populated) - len(report.invalid_fields)) / len(populated) if populated else 0.0
    )
    report.consistency_score = (
        (len(populated) - len(report.conflicting_fields)) / len(populated) if populated else 0.0
    )
    report.overall_quality_score = 100 * (
        (report.completeness_score + report.validity_score + report.consistency_score) / 3
    )
    return report
