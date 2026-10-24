
import unittest

from api_agent import _validate_result, generate_migration


class ValidateResultTests(unittest.TestCase):
    def setUp(self):
        self.source = "client.old_call()"
        self.valid_result = {
            "breaking_change": True,
            "affected": True,
            "affected_usages": ["old_call"],
            "updated_code": "client.new_call()",
            "explanation": "The old method was removed.",
            "confidence": 0.9,
            "assumptions": [],
        }

    def test_valid_result_keeps_proposed_patch(self):
        result = _validate_result(self.valid_result.copy(), self.source)

        self.assertEqual(result["updated_code"], "client.new_call()")
        self.assertTrue(result["affected"])

    def test_no_affected_usage_cannot_change_code(self):
        result_data = self.valid_result.copy()
        result_data.update({
            "affected": False,
            "affected_usages": [],
            "updated_code": "dangerous invented edit()",
        })

        result = _validate_result(result_data, "print('hello')")

        self.assertEqual(result["updated_code"], "print('hello')")

    def test_missing_required_key_fails(self):
        with self.assertRaises(ValueError):
            _validate_result({"affected": False}, "print('x')")

    def test_empty_input_fails_before_api_call(self):
        with self.assertRaises(ValueError):
            generate_migration("", "print('hello')")

    def test_invalid_confidence_is_rejected(self):
        result_data = self.valid_result.copy()
        result_data["confidence"] = 1.5

        with self.assertRaises(ValueError):
            _validate_result(result_data, self.source)

    def test_invalid_boolean_field_is_rejected(self):
        result_data = self.valid_result.copy()
        result_data["affected"] = "yes"

        with self.assertRaises(ValueError):
            _validate_result(result_data, self.source)

    def test_invalid_list_field_is_rejected(self):
        result_data = self.valid_result.copy()
        result_data["affected_usages"] = "old_call"

        with self.assertRaises(ValueError):
            _validate_result(result_data, self.source)

    
    def test_unaffected_code_is_preserved_exactly(self):
        source = "\ndef greet(name):\n    return name\n\n"
        result_data = self.valid_result.copy()
        result_data.update({
            "affected": False,
            "affected_usages": [],
            "updated_code": "some changed code",
        })

        result = _validate_result(result_data, source)

        self.assertFalse(result["affected"])
        self.assertEqual(result["affected_usages"], [])
        self.assertEqual(result["updated_code"], source)

    def test_affected_without_usages_is_rejected_as_unaffected(self):
        source = "client.create_charge(100, 'USD')"
        result_data = self.valid_result.copy()
        result_data.update({
            "affected": True,
            "affected_usages": [],
            "updated_code": "client.create_payment(10000, 'USD')",
        })

        result = _validate_result(result_data, source)

        self.assertFalse(result["affected"])
        self.assertEqual(result["updated_code"], source)



if __name__ == "__main__":
    unittest.main()
