import unittest
from src.normalization import normalize_email, normalize_phone, normalize_name, normalize_list


class TestNormalization(unittest.TestCase):
    def test_email_lowercased_and_trimmed(self):
        self.assertEqual(normalize_email("  Jane.Doe@EXAMPLE.com "), "jane.doe@example.com")

    def test_email_none(self):
        self.assertIsNone(normalize_email(None))

    def test_phone_strips_formatting(self):
        self.assertEqual(normalize_phone("+1 (415) 555-0198"), "+14155550198")

    def test_phone_no_plus(self):
        self.assertEqual(normalize_phone("415-555-0198"), "4155550198")

    def test_name_title_cases(self):
        self.assertEqual(normalize_name("jane doe"), "Jane Doe")

    def test_list_from_csv_string(self):
        self.assertEqual(normalize_list("Python, Go, AWS"), ["Python", "Go", "AWS"])

    def test_list_passthrough(self):
        self.assertEqual(normalize_list(["Python", " Go "]), ["Python", "Go"])


if __name__ == "__main__":
    unittest.main()
