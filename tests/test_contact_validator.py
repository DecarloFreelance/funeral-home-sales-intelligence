import unittest

from validation.contact_validator import validate_phone


class ValidatePhoneTests(unittest.TestCase):
    # Regression coverage for the false-negative defect: validate_phone()
    # used to reject any digit string starting with "19" or "20" as a
    # suspected timestamp/ID, which also rejected every real 200-209 area
    # code -- including 204 (Manitoba). Traced end-to-end against real V26
    # crawl evidence: PHONE_PATTERN correctly matched numbers like
    # "204.827.2480" and "(204) 871-5700", but validate_phone() silently
    # discarded all of them before they reached the findings layer.
    def test_manitoba_204_area_code_with_dot_separators_is_valid(self):
        self.assertTrue(validate_phone("204.827.2480"))

    def test_manitoba_204_area_code_with_dash_separators_is_valid(self):
        self.assertTrue(validate_phone("204-505-4559"))

    def test_manitoba_204_area_code_with_parens_and_space_is_valid(self):
        self.assertTrue(validate_phone("(204) 871-5700"))

    def test_other_previously_rejected_200_series_area_codes_are_valid(self):
        # 202 (Washington DC), 205 (Alabama), 209 (California) -- all real,
        # all previously rejected by the "starts with 20" heuristic.
        self.assertTrue(validate_phone("202-555-0134"))
        self.assertTrue(validate_phone("205-555-0134"))
        self.assertTrue(validate_phone("209-555-0134"))

    def test_leading_1_country_code_still_normalizes_correctly(self):
        self.assertTrue(validate_phone("1-204-827-2480"))
        self.assertTrue(validate_phone("+1 204 827 2480"))

    def test_11_digit_number_not_starting_with_1_is_still_rejected(self):
        self.assertFalse(validate_phone("22048272480"))

    def test_area_code_starting_with_0_or_1_is_still_rejected(self):
        self.assertFalse(validate_phone("012-345-6789"))
        self.assertFalse(validate_phone("112-345-6789"))

    def test_wrong_length_is_still_rejected(self):
        self.assertFalse(validate_phone("204-827-248"))
        self.assertFalse(validate_phone("204-827-24800"))

    def test_empty_or_falsy_input_is_rejected(self):
        self.assertFalse(validate_phone(""))
        self.assertFalse(validate_phone(None))


if __name__ == "__main__":
    unittest.main()
