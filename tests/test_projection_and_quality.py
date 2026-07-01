import unittest
from src.models import CanonicalCandidate, FieldValue, ProvenanceRecord
from src.projection import project, validate_projection_schema
from src.reports.quality import build_quality_report


def _fv(name, value, source="structured", confidence=0.9, conflict=False):
    ev = ProvenanceRecord(source=source, extraction_method="test", raw_value=value,
                           normalized_value=value, valid=True)
    return FieldValue(name=name, value=value, confidence=confidence, winning_source=source,
                       evidence=[ev], conflict=conflict)


class TestProjection(unittest.TestCase):
    def test_projection_maps_fields(self):
        canonical = CanonicalCandidate(
            fields={
                "candidate_id": _fv("candidate_id", "C-1"),
                "full_name": _fv("full_name", "Jane Doe"),
                "email": _fv("email", "jane@doe.com"),
            },
            identity_resolution={"candidate_id": "C-1"},
        )
        proj = project(canonical)
        self.assertEqual(proj.candidate_id, "C-1")
        self.assertEqual(proj.full_name, "Jane Doe")
        self.assertEqual(proj.skills, [])  # default empty list, never None

    def test_schema_validation_passes_for_good_projection(self):
        canonical = CanonicalCandidate(
            fields={"candidate_id": _fv("candidate_id", "C-1")},
            identity_resolution={"candidate_id": "C-1"},
        )
        proj = project(canonical)
        errors = validate_projection_schema(proj)
        self.assertEqual(errors, [])

    def test_schema_validation_catches_bad_confidence(self):
        canonical = CanonicalCandidate(
            fields={"candidate_id": _fv("candidate_id", "C-1", confidence=1.5)},
            identity_resolution={"candidate_id": "C-1"},
        )
        proj = project(canonical)
        errors = validate_projection_schema(proj)
        self.assertTrue(any("out of [0,1]" in e for e in errors))


class TestQualityReport(unittest.TestCase):
    def test_missing_fields_detected(self):
        canonical = CanonicalCandidate(
            fields={"candidate_id": _fv("candidate_id", "C-1"), "full_name": _fv("full_name", "Jane")},
        )
        report = build_quality_report(canonical, "C-1")
        self.assertIn("email", report.missing_fields)
        self.assertGreater(report.overall_quality_score, 0)

    def test_conflict_detected_in_report(self):
        fv = _fv("phone", "111", conflict=True)
        fv.conflicting_values = ["222"]
        canonical = CanonicalCandidate(fields={"candidate_id": _fv("candidate_id", "C-1"), "phone": fv})
        report = build_quality_report(canonical, "C-1")
        self.assertEqual(len(report.conflicting_fields), 1)


if __name__ == "__main__":
    unittest.main()
