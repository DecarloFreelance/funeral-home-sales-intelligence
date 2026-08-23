import unittest

from discovery.providers.afsa import (
    DIRECTORY_URL,
    AfsaDirectoryClient,
    parse_directory_pages,
    parse_member_page,
)


INDEX_HTML = """
<html><body>
  <a href="/a-b">View List</a>
  <a href="https://www.afsa.ca/c-d">View List</a>
  <a href="https://outside.example/list">View List</a>
</body></html>
"""

MEMBER_HTML = """
<html><body>
  <div class="dmRespRow">
    <div><h3>Bashaw</h3></div>
    <div>
      <ul class="accordion-wrapper">
        <li class="accordion-item">
          <div class="accordion-title">
            <div class="title-text"><div>Bashaw Funeral Home</div></div>
          </div>
          <div class="accordion-description"><div class="section-inner">
            <p>5016 - 50 Avenue Bashaw AB T0B 0H0</p>
            <p>Phone: <a href="tel:780-372-2353">780-372-2353</a></p>
            <p>Website: <a href="http://www.example.com/bashaw">example.com</a></p>
            <p>Email: care@example.com</p>
          </div></div>
        </li>
      </ul>
    </div>
  </div>
</body></html>
"""


class FakeResponse:

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeSession:

    def __init__(self, responses):
        self.responses = responses
        self.headers = {}
        self.requested = []

    def get(self, url, timeout):
        self.requested.append((url, timeout))
        return FakeResponse(self.responses[url])


class AfsaProviderTests(unittest.TestCase):

    def test_directory_page_discovery_stays_on_official_domain(self):
        self.assertEqual(parse_directory_pages(INDEX_HTML), [
            "https://www.afsa.ca/a-b",
            "https://www.afsa.ca/c-d",
        ])

    def test_member_parser_extracts_public_business_fields(self):
        records = parse_member_page(MEMBER_HTML, "https://www.afsa.ca/a-b")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["company"], "Bashaw Funeral Home")
        self.assertEqual(records[0]["city"], "Bashaw")
        self.assertEqual(records[0]["phone"], "780-372-2353")
        self.assertEqual(records[0]["website"], "http://www.example.com/bashaw")
        self.assertEqual(records[0]["email"], "care@example.com")
        self.assertEqual(records[0]["province"], "AB")

    def test_client_discovers_pages_and_combines_members(self):
        session = FakeSession({
            DIRECTORY_URL: INDEX_HTML,
            "https://www.afsa.ca/a-b": MEMBER_HTML,
            "https://www.afsa.ca/c-d": MEMBER_HTML.replace("Bashaw", "Calgary"),
        })
        client = AfsaDirectoryClient(session=session, timeout=7, delay=0)

        records = client.fetch()

        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]["city"], "Calgary")
        self.assertEqual(len(session.requested), 3)
        self.assertTrue(session.headers["User-Agent"])


if __name__ == "__main__":
    unittest.main()
