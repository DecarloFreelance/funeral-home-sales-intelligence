import unittest
from unittest.mock import MagicMock, patch

from discovery.langsearch_provider import LangSearchError, LangSearchProvider


def _fake_response(status_code=200, json_body=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_body is None:
        response.json.side_effect = ValueError("no body")
    else:
        response.json.return_value = json_body
    return response


class LangSearchProviderTests(unittest.TestCase):
    def test_missing_api_key_raises_without_network_call(self):
        session = MagicMock()
        provider = LangSearchProvider(api_key="", session=session)

        with self.assertRaises(LangSearchError):
            provider.search("Example Funeral Home Town Province Canada")

        session.post.assert_not_called()

    def test_blank_query_is_rejected(self):
        provider = LangSearchProvider(api_key="key", session=MagicMock())
        with self.assertRaises(ValueError):
            provider.search("   ")

    def test_successful_search_normalizes_results(self):
        session = MagicMock()
        session.post.return_value = _fake_response(
            json_body={
                "code": 200,
                "log_id": "abc123",
                "msg": None,
                "data": {
                    "webPages": {
                        "totalEstimatedMatches": 1,
                        "value": [
                            {
                                "id": "1",
                                "name": "Example Funeral Home",
                                "url": "https://example.test/",
                                "displayUrl": "example.test",
                                "snippet": "Serving Example Town since 1950.",
                            },
                            {"name": "no url dropped"},
                        ],
                    }
                },
            }
        )
        provider = LangSearchProvider(api_key="key", min_interval=0, session=session)

        result = provider.search("Example Funeral Home Example Town Canada", limit=5)

        self.assertEqual(result["log_id"], "abc123")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["url"], "https://example.test/")
        self.assertEqual(result["results"][0]["title"], "Example Funeral Home")

        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"]["count"], 5)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer key")

    def test_non_200_status_raises(self):
        session = MagicMock()
        session.post.return_value = _fake_response(status_code=401, text="unauthorized")
        provider = LangSearchProvider(api_key="bad-key", min_interval=0, session=session)

        with self.assertRaises(LangSearchError):
            provider.search("query")

    def test_non_json_body_raises(self):
        session = MagicMock()
        session.post.return_value = _fake_response(status_code=200, json_body=None)
        provider = LangSearchProvider(api_key="key", min_interval=0, session=session)

        with self.assertRaises(LangSearchError):
            provider.search("query")

    def test_provider_error_code_raises(self):
        session = MagicMock()
        session.post.return_value = _fake_response(
            json_body={"code": 429, "msg": "rate limited", "data": {}}
        )
        provider = LangSearchProvider(api_key="key", min_interval=0, session=session)

        with self.assertRaises(LangSearchError):
            provider.search("query")

    def test_request_exception_wrapped_as_langsearch_error(self):
        import requests

        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")
        provider = LangSearchProvider(api_key="key", min_interval=0, session=session)

        with self.assertRaises(LangSearchError):
            provider.search("query")

    def test_min_interval_throttles_between_calls(self):
        session = MagicMock()
        session.post.return_value = _fake_response(
            json_body={"code": 200, "log_id": "x", "data": {"webPages": {"value": []}}}
        )
        provider = LangSearchProvider(api_key="key", min_interval=5, session=session)

        # Three time.monotonic() reads happen in this scenario: recording
        # the timestamp after call 1's request, checking elapsed time at the
        # top of call 2's throttle, and recording the timestamp after call
        # 2's request. One second elapses between the first and second.
        with patch("discovery.langsearch_provider.time.monotonic", side_effect=[100.0, 101.0, 102.0]), \
             patch("discovery.langsearch_provider.time.sleep") as mocked_sleep:
            provider.search("first")
            provider.search("second")

        mocked_sleep.assert_called_once()
        (slept_for,), _ = mocked_sleep.call_args
        self.assertAlmostEqual(slept_for, 4.0, places=3)


if __name__ == "__main__":
    unittest.main()
