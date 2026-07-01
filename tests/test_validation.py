import unittest
from src.validation import validate_email, validate_phone, validate_years_experience, cross_field_validate


class TestValidation(unittest.TestCase):
    def test_valid_email(self):
        self.assertTrue(validate_email("a@b.com").valid)

    def test_invalid_email(self):
        self.assertFalse(validate_email("not-an-email").valid)

    def test_missing_email(self):
        self.assertFalse(validate_email(None).valid)

    def test_valid_phone(self):
        self.assertTrue(validate_phone("+14155550198").valid)

    def test_invalid_phone_letters(self):
        self.assertFalse(validate_phone("abc-not-a-number").valid)

    def test_years_experience_range(self):
        self.assertTrue(validate_years_experience(5).valid)
        self.assertFalse(validate_years_experience(200).valid)
        self.assertFalse(validate_years_experience(-1).valid)

    def test_cross_field_seniority_mismatch(self):
        warnings = cross_field_validate({"current_title": "Senior Engineer", "years_experience": 1})
        self.assertTrue(any("suggests seniority" in w for w in warnings))

    def test_cross_field_placeholder_email(self):
        warnings = cross_field_validate({"email": "a@example.com"})
        self.assertTrue(any("placeholder" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
