
import ast
import json
import unittest
from unittest.mock import patch

from api_agent import (
    RESPONSE_SCHEMA,
    _validate_result,
    audit_api_source,
    generate_migration,
    has_candidate_api_usage,
)


class AutomaticAuditTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def test_audit_keeps_only_findings_with_exact_source_evidence(self):
        source = "notion.databases.query(database_id=database_id)\n"
        valid_finding = {
            "title": "Use a data source query",
            "severity": "high",
            "evidence": "notion.databases.query(database_id=database_id)",
            "explanation": "Database queries moved to data sources.",
            "recommendation": "Query with a data_source_id.",
            "proposed_code": "notion.data_sources.query(data_source_id=data_source_id)\n",
            "patch_before": "",
            "patch_after": "",
        }
        payload = {"message": {"content": json.dumps({
            "api_detected": True,
            "api_usages": [valid_finding["evidence"], "invented.call()"],
            "findings": [valid_finding, {**valid_finding, "evidence": "invented.call()"}],
        })}}
        with patch("api_agent.urlopen", return_value=self.FakeResponse(payload)):
            result = audit_api_source(source, "tasks.py", "notion-client==2.5.0")

        self.assertTrue(result["api_detected"])
        self.assertEqual(result["api_usages"], [valid_finding["evidence"]])
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["title"], valid_finding["title"])

    def test_empty_source_does_not_call_ollama(self):
        with patch("api_agent.urlopen") as mocked:
            result = audit_api_source("  \n", "empty.py")
        self.assertFalse(result["api_detected"])
        mocked.assert_not_called()

    def test_unique_patch_snippet_builds_updated_python_source(self):
        source = "client.old_call()\n"
        finding = {
            "title": "Replace removed method", "severity": "high",
            "evidence": "client.old_call()", "explanation": "Method removed.",
            "recommendation": "Use new_call.", "proposed_code": "",
            "patch_before": "client.old_call()", "patch_after": "client.new_call()",
        }
        response = {"message": {"content": json.dumps({
            "api_detected": True, "api_usages": [finding["evidence"]], "findings": [finding],
        })}}
        with patch("api_agent.urlopen", return_value=self.FakeResponse(response)):
            result = audit_api_source(source, "client.py")
        self.assertEqual(result["findings"][0]["proposed_code"], "client.new_call()\n")

    def test_ambiguous_patch_is_rejected(self):
        source = "client.old_call()\nclient.old_call()\n"
        finding = {
            "title": "Replace removed method", "severity": "high",
            "evidence": "client.old_call()", "explanation": "Method removed.",
            "recommendation": "Use new_call.", "proposed_code": "",
            "patch_before": "client.old_call()", "patch_after": "client.new_call()",
        }
        response = {"message": {"content": json.dumps({
            "api_detected": True, "api_usages": [finding["evidence"]], "findings": [finding],
        })}}
        with patch("api_agent.urlopen", return_value=self.FakeResponse(response)):
            result = audit_api_source(source, "client.py")
        self.assertEqual(result["findings"][0]["proposed_code"], "")
        self.assertEqual(result["findings"][0]["patch_before"], "")

    def test_generic_latest_version_speculation_is_not_reported_as_issue(self):
        source = "async with httpx.AsyncClient() as client:\n    pass\n"
        finding = {
            "title": "Incompatible API Version", "severity": "high",
            "evidence": "httpx.AsyncClient", "explanation": (
                "The latest version may have breaking changes or deprecated methods."
            ), "recommendation": "Upgrade to the latest version.",
            "proposed_code": "", "patch_before": "", "patch_after": "",
        }
        response = {"message": {"content": json.dumps({
            "api_detected": True, "api_usages": ["httpx.AsyncClient"], "findings": [finding],
        })}}
        with patch("api_agent.urlopen", return_value=self.FakeResponse(response)):
            result = audit_api_source(source, "client.py", "httpx<1")
        self.assertEqual(result["findings"], [])


class ValidateResultTests(unittest.TestCase):
    def setUp(self):
        self.source = "client.old_call()"
        self.valid_result = {
            "breaking_change": True,
            "affected": True,
            "affected_usages": ["old_call"],
            "edits": [{
                "before": "client.old_call()",
                "after": "client.new_call()",
            }],
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

        with self.assertRaises(TypeError):
            _validate_result(result_data, self.source)

    def test_invalid_list_field_is_rejected(self):
        result_data = self.valid_result.copy()
        result_data["affected_usages"] = "old_call"

        with self.assertRaises(TypeError):
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

    def test_affected_without_usages_is_rejected(self):
        source = "client.create_charge(100, 'USD')"
        result_data = self.valid_result.copy()
        result_data.update({
            "affected": True,
            "affected_usages": [],
            "edits": [{
                "before": "client.old_call()",
                "after": "client.create_payment(10000, 'USD')",
            }],
        })

        with self.assertRaises(ValueError):
            _validate_result(result_data, source)

    def test_edit_must_match_exactly_once(self):
        source = "client.old_call()\nclient.old_call()\n"
        with self.assertRaisesRegex(ValueError, "exactly once"):
            _validate_result(self.valid_result.copy(), source)

    def test_persistently_ambiguous_edit_becomes_safe_noop(self):
        source = "client.old_call()\nclient.old_call()\n"
        result = _validate_result(
            self.valid_result.copy(),
            source,
            allow_ambiguous_noop=True,
        )

        self.assertFalse(result["affected"])
        self.assertEqual(result["updated_code"], source)
        self.assertIn("unique source location", result["explanation"])

    def test_explicit_keyword_rename_uses_exact_python_call(self):
        source = (
            "retry = Retry(total=3, "
            "method_whitelist=frozenset(['GET', 'POST']))\n"
        )
        changelog = (
            "Replace Retry(method_whitelist=...) with "
            "Retry(allowed_methods=...)."
        )
        result_data = self.valid_result.copy()
        result_data["edits"] = [{
            "before": "method_whitelist=...",
            "after": "allowed_methods=...",
        }]

        result = _validate_result(result_data, source, changelog)

        self.assertIn("allowed_methods=frozenset(['GET', 'POST'])", result["updated_code"])
        self.assertNotIn("method_whitelist=", result["updated_code"])
        ast.parse(result["updated_code"])

    def test_explicit_single_proxy_rename_handles_repeated_calls(self):
        source = (
            'first = httpx.Client(proxies="http://one")\n'
            'second = httpx.Client(proxies="http://two")\n'
        )
        changelog = (
            "HTTPX 0.28 removed the deprecated proxies argument. Replace "
            "single proxy configurations with proxy= and multiple proxy "
            "configurations with mounts=."
        )
        result_data = self.valid_result.copy()
        result_data["edits"] = [{"before": "proxies=", "after": "proxy="}]

        result = _validate_result(result_data, source, changelog)

        self.assertIn('Client(proxy="http://one")', result["updated_code"])
        self.assertIn('Client(proxy="http://two")', result["updated_code"])
        ast.parse(result["updated_code"])

    def test_response_schema_requires_every_contract_field(self):
        self.assertEqual(set(RESPONSE_SCHEMA["required"]), {
            "breaking_change",
            "affected",
            "affected_usages",
            "edits",
            "explanation",
            "confidence",
            "assumptions",
        })
        self.assertFalse(RESPONSE_SCHEMA["additionalProperties"])

    def test_keyword_argument_usage_is_detected(self):
        source = "Retry(total=3, method_whitelist=frozenset(['GET']))"
        changelog = (
            "Retry(method_whitelist=...) was removed; use "
            "Retry(allowed_methods=...)."
        )

        self.assertTrue(has_candidate_api_usage(source, changelog))

    def test_unrelated_source_is_not_a_candidate(self):
        source = "def greet(name):\n    return name\n"
        changelog = "Retry(method_whitelist=...) was removed."

        self.assertFalse(has_candidate_api_usage(source, changelog))

    def test_proxy_argument_on_other_client_library_is_not_a_candidate(self):
        source = "aiohttp.ClientSession(proxy=proxy_url)\n"
        changelog = (
            "HTTPX 0.28 removed the deprecated proxies argument from "
            "httpx.AsyncClient. Replace it with proxy= or mounts=."
        )

        self.assertFalse(has_candidate_api_usage(source, changelog))

    def test_named_httpx_client_old_keyword_is_a_candidate(self):
        source = "httpx.AsyncClient(proxies=proxy_map)\n"
        changelog = (
            "HTTPX 0.28 removed the deprecated proxies argument from "
            "httpx.AsyncClient. Replace it with proxy= or mounts=."
        )

        self.assertTrue(has_candidate_api_usage(source, changelog))

    def test_incomplete_model_response_is_retried_with_schema(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        invalid = FakeResponse({"message": {"content": '{"affected":false}'}})
        valid = FakeResponse({
            "message": {"content": json.dumps(self.valid_result)}
        })
        with patch("api_agent.urlopen", side_effect=[invalid, valid]) as mocked:
            result = generate_migration(
                "old_call() was removed; use new_call()",
                self.source,
            )

        self.assertTrue(result["affected"])
        self.assertEqual(mocked.call_count, 2)
        first_request = json.loads(mocked.call_args_list[0].args[0].data)
        self.assertEqual(first_request["format"], RESPONSE_SCHEMA)
        self.assertEqual(first_request["options"]["num_ctx"], 32768)

    def test_ambiguous_edit_retry_includes_validation_feedback(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        source = "client.old_call()\nclient.old_call()\n"
        ambiguous = self.valid_result.copy()
        corrected = self.valid_result.copy()
        corrected["edits"] = [{
            "before": source,
            "after": "client.new_call()\nclient.new_call()\n",
        }]
        responses = [
            FakeResponse({"message": {"content": json.dumps(ambiguous)}}),
            FakeResponse({"message": {"content": json.dumps(corrected)}}),
        ]

        with patch("api_agent.urlopen", side_effect=responses) as mocked:
            result = generate_migration(
                "old_call() was removed; use new_call()",
                source,
            )

        self.assertEqual(
            result["updated_code"],
            "client.new_call()\nclient.new_call()\n",
        )
        self.assertEqual(mocked.call_count, 2)
        retry_request = json.loads(mocked.call_args_list[1].args[0].data)
        retry_feedback = retry_request["messages"][-1]["content"]
        self.assertIn("failed validation", retry_feedback)
        self.assertIn("occurs exactly once", retry_feedback)



if __name__ == "__main__":
    unittest.main()
