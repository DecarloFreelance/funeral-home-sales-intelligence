import unittest

import requests

from discovery.crawler import PriorityPageCrawler


class FakeResponse:

    def __init__(self, url, text="", status=200, content_type="text/html"):
        self.url = url
        self.text = text
        self.status_code = status
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(str(self.status_code))
            error.response = self
            raise error


class FakeSession:

    def __init__(self, responses):
        self.responses = responses
        self.headers = {}
        self.requested = []

    def get(self, url, timeout):
        self.requested.append((url, timeout))
        response = self.responses.get(url)
        if response is None:
            raise requests.ConnectionError(url)
        return response


class PriorityPageCrawlerTests(unittest.TestCase):

    def test_crawls_homepage_and_discovers_priority_same_domain_link(self):
        homepage = "https://example.com/"
        contact = "https://example.com/contact-us"
        session = FakeSession({
            homepage: FakeResponse(homepage, """
                <html><head>
                  <title>Example Funeral Home</title>
                  <meta name="description" content="Serving Edmonton">
                  <script type="application/ld+json">
                    {"@type":"FuneralHome","name":"Example Funeral Home"}
                  </script>
                </head><body>
                  <a href="/contact-us">Contact our team</a>
                  <a href="https://outside.example/team">External team</a>
                </body></html>
            """),
            contact: FakeResponse(
                contact,
                "<html><body>Call (780) 555-1234</body></html>",
            ),
        })
        crawler = PriorityPageCrawler(session=session, timeout=3, max_pages_per_lead=5)

        records = crawler.crawl_lead({
            "company": "Example Funeral Home",
            "domain": "example.com",
            "url": homepage,
            "priority_urls": [],
            "source": "manual",
            "email": "directory@example.com",
            "locations": [{"company": "Example Funeral Home", "city": "Edmonton"}],
        })

        self.assertEqual([record["url"] for record in records], [homepage, contact])
        self.assertEqual(records[0]["metadata"]["title"], "Example Funeral Home")
        self.assertEqual(
            records[0]["metadata"]["jsonLd"][0]["@type"],
            "FuneralHome",
        )
        self.assertIn("Call (780) 555-1234", records[1]["markdown"])
        self.assertEqual(records[1]["discovery"]["source"], "manual")
        self.assertEqual(records[0]["discovery"]["email"], "directory@example.com")
        self.assertEqual(records[0]["discovery"]["locations"][0]["city"], "Edmonton")

    def test_skips_failures_non_html_and_cross_domain_redirects(self):
        session = FakeSession({
            "https://example.com/": FakeResponse(
                "https://other.example/", "<html>Redirected</html>"
            ),
            "https://example.com/contact": FakeResponse(
                "https://example.com/contact", "PDF", content_type="application/pdf"
            ),
            "https://example.com/about": FakeResponse(
                "https://example.com/about", status=500
            ),
        })
        crawler = PriorityPageCrawler(session=session)

        records = crawler.crawl_lead({
            "domain": "example.com",
            "url": "https://example.com/",
            "priority_urls": [
                "https://example.com/contact",
                "https://example.com/about",
                "https://outside.example/team",
            ],
        })

        self.assertEqual(records, [])
        self.assertNotIn(
            ("https://outside.example/team", 15),
            session.requested,
        )
        self.assertEqual(crawler.last_lead_report["status"], "FAILED")
        self.assertTrue(any(
            attempt.get("status_code") == 500
            for attempt in crawler.last_lead_report["attempts"]
        ))

    def test_rejects_invalid_or_mismatched_queue_record(self):
        session = FakeSession({})
        crawler = PriorityPageCrawler(session=session)

        self.assertEqual(crawler.crawl_lead({"domain": "example.com"}), [])
        self.assertEqual(crawler.crawl_lead({
            "domain": "example.com",
            "url": "https://other.example/",
        }), [])
        self.assertEqual(session.requested, [])

    def test_queue_report_identifies_domains_without_pages(self):
        homepage = "https://example.com/"
        session = FakeSession({
            homepage: FakeResponse(homepage, "<html><body>Home</body></html>"),
        })
        crawler = PriorityPageCrawler(session=session)

        crawler.crawl_queue([
            {"domain": "example.com", "url": homepage},
            {"domain": "failed.example", "url": "https://failed.example/"},
        ])

        self.assertEqual(crawler.last_report["queued_domains"], 2)
        self.assertEqual(crawler.last_report["successful_domains"], 1)
        self.assertEqual(crawler.last_report["failed_domains"], ["failed.example"])

    def test_queue_progress_callback_receives_each_domain(self):
        homepage = "https://example.com/"
        session = FakeSession({
            homepage: FakeResponse(homepage, "<html><body>Home</body></html>"),
        })
        crawler = PriorityPageCrawler(session=session)
        progress = []

        crawler.crawl_queue(
            [{"domain": "example.com", "url": homepage}],
            on_lead=lambda *values: progress.append(values),
        )

        self.assertEqual(progress, [(1, 1, "example.com", 1)])

    def test_allows_same_brand_homepage_redirect_to_country_domain(self):
        session = FakeSession({
            "https://example.com/": FakeResponse(
                "https://www.example.ca/en.html",
                "<html><body><a href='/contact'>Contact</a></body></html>",
            ),
            "https://www.example.ca/contact": FakeResponse(
                "https://www.example.ca/contact",
                "<html><body>Contact page</body></html>",
            ),
        })
        crawler = PriorityPageCrawler(session=session)

        records = crawler.crawl_lead({
            "domain": "example.com",
            "url": "https://example.com/",
        })

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["url"], "https://www.example.ca/en.html")


if __name__ == "__main__":
    unittest.main()
