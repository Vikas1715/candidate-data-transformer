import unittest
import time
from src.models import RawRecord
from src.merge import merge_field
from src.confidence import score_field, score_all
from src.config import Config


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def test_single_source_wins_trivially(self):
        records = [RawRecord("structured", "csv", "x.csv", {"email": "a@b.com"}, "csv.DictReader")]
        fv = merge_field("email", records, self.config)
        self.assertEqual(fv.value, "a@b.com")
        self.assertFalse(fv.conflict)

    def test_agreement_no_conflict(self):
        records = [
            RawRecord("structured", "csv", "x.csv", {"email": "a@b.com"}, "csv"),
            RawRecord("resume", "txt", "x.txt", {"email": "A@B.com"}, "regex"),
        ]
        fv = merge_field("email", records, self.config)
        self.assertFalse(fv.conflict)
        self.assertEqual(fv.value, "a@b.com")

    def test_conflict_resolved_by_trust(self):
        records = [
            RawRecord("notes", "txt", "n.txt", {"phone": "111-111-1111"}, "regex"),
            RawRecord("structured", "csv", "s.csv", {"phone": "222-222-2222"}, "csv"),
        ]
        fv = merge_field("phone", records, self.config)
        self.assertTrue(fv.conflict)
        self.assertEqual(fv.winning_source, "structured")  # higher trust wins
        self.assertIn("2222222222", fv.value)

    def test_losing_evidence_preserved(self):
        records = [
            RawRecord("notes", "txt", "n.txt", {"phone": "111-111-1111"}, "regex"),
            RawRecord("structured", "csv", "s.csv", {"phone": "222-222-2222"}, "csv"),
        ]
        fv = merge_field("phone", records, self.config)
        sources_in_evidence = {e.source for e in fv.evidence}
        self.assertEqual(sources_in_evidence, {"notes", "structured"})  # nothing dropped

    def test_invalid_value_loses_to_valid_lower_trust(self):
        records = [
            RawRecord("structured", "csv", "s.csv", {"email": "not-an-email"}, "csv"),
            RawRecord("notes", "txt", "n.txt", {"email": "valid@example.com"}, "regex"),
        ]
        fv = merge_field("email", records, self.config)
        self.assertEqual(fv.winning_source, "notes")


class TestConfidence(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def test_missing_field_zero_confidence(self):
        records = []
        fv = merge_field("email", records, self.config)
        self.assertEqual(score_field(fv, self.config), 0.0)

    def test_conflict_lowers_confidence_vs_agreement(self):
        agree = [
            RawRecord("structured", "csv", "s", {"phone": "1112223333"}, "csv"),
            RawRecord("resume", "txt", "r", {"phone": "1112223333"}, "regex"),
        ]
        conflict = [
            RawRecord("structured", "csv", "s", {"phone": "1112223333"}, "csv"),
            RawRecord("resume", "txt", "r", {"phone": "9998887777"}, "regex"),
        ]
        fv_agree = merge_field("phone", agree, self.config)
        fv_conflict = merge_field("phone", conflict, self.config)
        c_agree = score_field(fv_agree, self.config)
        c_conflict = score_field(fv_conflict, self.config)
        self.assertGreater(c_agree, c_conflict)

    def test_confidence_bounded(self):
        records = [RawRecord("structured", "csv", "s", {"email": "a@b.com"}, "csv")]
        fv = merge_field("email", records, self.config)
        c = score_field(fv, self.config)
        self.assertGreaterEqual(c, self.config.min_confidence)
        self.assertLessEqual(c, self.config.max_confidence)


if __name__ == "__main__":
    unittest.main()
