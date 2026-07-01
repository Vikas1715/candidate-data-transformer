import unittest
from src.identity import resolve_hierarchy, resolve_composite_score


class TestIdentityHierarchy(unittest.TestCase):
    def test_explicit_id_wins(self):
        sources = {"structured": {"candidate_id": "C-1", "email": "a@b.com"}}
        r = resolve_hierarchy(sources)
        self.assertEqual(r.candidate_id, "C-1")
        self.assertTrue(r.resolved)
        self.assertIn("explicit_id", r.resolution_path)

    def test_falls_back_to_email(self):
        sources = {"resume": {"email": "jane@doe.com"}}
        r = resolve_hierarchy(sources)
        self.assertEqual(r.candidate_id, "jane@doe.com")
        self.assertTrue(r.resolved)

    def test_falls_back_to_phone(self):
        sources = {"notes": {"phone": "+14155550198"}}
        r = resolve_hierarchy(sources)
        self.assertEqual(r.candidate_id, "+14155550198")

    def test_falls_back_to_github(self):
        sources = {"resume": {"github_username": "janedoe"}}
        r = resolve_hierarchy(sources)
        self.assertEqual(r.candidate_id, "gh:janedoe")

    def test_unresolved_is_deterministic(self):
        sources = {"resume": {"full_name": "No Identifiers Here"}}
        r1 = resolve_hierarchy(sources)
        r2 = resolve_hierarchy(sources)
        self.assertFalse(r1.resolved)
        self.assertEqual(r1.candidate_id, r2.candidate_id)  # deterministic re-run

    def test_no_fuzzy_matching_used(self):
        # Two clearly-the-same-person-but-differently-typed names must NOT
        # resolve to the same id via name alone -- only exact identifiers do.
        sources_a = {"resume": {"full_name": "Jon Smith"}}
        sources_b = {"resume": {"full_name": "John Smith"}}
        ra = resolve_hierarchy(sources_a)
        rb = resolve_hierarchy(sources_b)
        self.assertNotEqual(ra.candidate_id, rb.candidate_id)


class TestIdentityComposite(unittest.TestCase):
    def test_corroborated_email_resolves(self):
        sources = {
            "structured": {"email": "a@b.com"},
            "resume": {"email": "a@b.com"},
        }
        r = resolve_composite_score(sources)
        self.assertTrue(r.resolved)
        self.assertGreaterEqual(r.composite_score, 0.5)

    def test_single_source_email_alone_not_enough(self):
        sources = {"resume": {"email": "a@b.com"}}
        r = resolve_composite_score(sources)
        self.assertFalse(r.resolved)


if __name__ == "__main__":
    unittest.main()
