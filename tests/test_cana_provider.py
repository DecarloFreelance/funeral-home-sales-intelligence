import unittest

from discovery.providers.cana import (
    CanaDirectoryClient, directory_url, is_target_provider, parse_results,
)


RESULTS_HTML = """
<div class="ListingResults_All_CONTAINER ListingResults_Level3_CONTAINER">
  <span itemprop="name"><a href="/canamembers/Funeral-Home/Example-1">Example Funeral Home</a></span>
  <div itemprop="address">
    <span itemprop="street-address">123 Main Street</span>
    <span itemprop="locality">Regina</span>
    <span itemprop="region">SK</span>
    <span itemprop="postal-code">S4P 1A1</span><span>Canada</span>
    <div class="ListingResults_Level3_MAINCONTACT">Jane Smith</div>
    <div class="ListingResults_Level3_PHONE1">(306) 555-9876</div>
  </div>
  <div class="ListingResults_Level3_AFFILIATIONS">
    <img class="ListingResults_Level3_AFFILIATIONICON" title="Funeral Home">
    <img class="ListingResults_Level3_AFFILIATIONICON" title="Crematory">
  </div>
  <span class="ListingResults_Level3_VISITSITE"><a href="https://example.com">Visit Site</a></span>
</div>
"""


class FakeResponse:
    def __init__(self, text=RESULTS_HTML):
        self.text = text

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, text=RESULTS_HTML):
        self.headers = {}
        self.calls = []
        self.text = text

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        return FakeResponse(self.text)


class FlakySession(FakeSession):
    def get(self, url, timeout):
        import requests
        self.calls.append((url, timeout))
        if len(self.calls) == 1:
            raise requests.Timeout("temporary")
        return FakeResponse()


class CanaProviderTests(unittest.TestCase):
    def test_parser_extracts_public_member_fields(self):
        records = parse_results(RESULTS_HTML, directory_url("Canada"))
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["company"], "Example Funeral Home")
        self.assertEqual(record["website"], "https://example.com")
        self.assertEqual(record["city"], "Regina")
        self.assertEqual(record["province"], "SK")
        self.assertEqual(record["phone"], "(306) 555-9876")
        self.assertEqual(record["contact_name"], "Jane Smith")
        self.assertEqual(record["category"], "Funeral Home, Crematory")
        self.assertTrue(record["source_url"].endswith("/Example-1"))

    def test_client_supports_controlled_country_list(self):
        session = FakeSession()
        records = CanaDirectoryClient(session=session, timeout=7, delay=0).fetch(
            ("Canada", "United States")
        )
        self.assertEqual(len(records), 2)
        self.assertIn("Country=Canada", session.calls[0][0])
        self.assertIn("Country=United+States", session.calls[1][0])
        self.assertEqual(session.calls[0][1], 7)
        self.assertTrue(session.headers["User-Agent"])

    def test_client_retries_transient_request_failure(self):
        session = FlakySession()
        records = CanaDirectoryClient(
            session=session, timeout=7, delay=0, retries=1
        ).fetch(("Canada",))
        self.assertEqual(len(records), 1)
        self.assertEqual(len(session.calls), 2)

    def test_parser_handles_repeated_country_results(self):
        records = parse_results(RESULTS_HTML * 200, directory_url("Canada"))
        self.assertEqual(len(records), 200)

    def test_non_provider_member_requires_explicit_inclusion(self):
        record = parse_results(
            RESULTS_HTML.replace('title="Funeral Home"', 'title="Industry Supplier"')
            .replace('title="Crematory"', 'title="Columbarium"'),
            directory_url("Canada"),
        )[0]
        self.assertFalse(is_target_provider(record))
        html = RESULTS_HTML.replace(
            'title="Funeral Home"', 'title="Industry Supplier"'
        ).replace('title="Crematory"', 'title="Columbarium"')
        client = CanaDirectoryClient(session=FakeSession(html), delay=0)
        self.assertEqual(client.fetch(("Canada",)), [])
        self.assertEqual(len(client.fetch(("Canada",), target_only=False)), 1)


if __name__ == "__main__":
    unittest.main()
