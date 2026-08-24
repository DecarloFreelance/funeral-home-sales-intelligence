import unittest

import requests

from discovery.crawler import PriorityPageCrawler


PUBLIC_RESOLVER = lambda hostname: ["93.184.216.34"]


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

    def get(self, url, timeout, allow_redirects=False):
        if allow_redirects:
            raise AssertionError("Crawler must authorize redirects itself")
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
        crawler = PriorityPageCrawler(session=session, timeout=3, max_pages_per_lead=5, host_resolver=PUBLIC_RESOLVER)

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
        self.assertRegex(records[0]["crawl"]["observedAt"], r"^\d{4}-\d{2}-\d{2}T.*Z$")

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
        crawler = PriorityPageCrawler(session=session, host_resolver=PUBLIC_RESOLVER)

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
        crawler = PriorityPageCrawler(session=session, host_resolver=PUBLIC_RESOLVER)

        self.assertEqual(crawler.crawl_lead({"domain": "example.com"}), [])
        self.assertEqual(crawler.crawl_lead({
            "domain": "example.com",
            "url": "https://other.example/",
        }), [])
        self.assertEqual(session.requested, [])

    def test_crawls_only_explicit_high_confidence_location_resolution_under_original_entity(self):
        target = "https://network.example/calgary/example-funeral-home/42"
        session = FakeSession({target: FakeResponse(target, "<html><body>Example Funeral Home Calgary <a href='/contact-us'>Contact</a></body></html>")})
        crawler = PriorityPageCrawler(session=session, host_resolver=PUBLIC_RESOLVER)
        lead = {
            "domain": "example.ca", "url": target,
            "resolution": {"outcome": "LOCATION_PAGE_CONFIRMED", "resolved": True,
                "confidence": 0.95, "official_website": target},
        }
        records = crawler.crawl_lead(lead)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["discovery"]["queue_domain"], "example.ca")
        self.assertEqual(records[0]["url"], target)
        self.assertEqual(session.requested, [(target, 15)])

        lead["resolution"]["confidence"] = 0.89
        self.assertEqual(crawler.crawl_lead(lead), [])

    def test_queue_report_identifies_domains_without_pages(self):
        homepage = "https://example.com/"
        session = FakeSession({
            homepage: FakeResponse(homepage, "<html><body>Home</body></html>"),
        })
        crawler = PriorityPageCrawler(session=session, host_resolver=PUBLIC_RESOLVER)

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
        crawler = PriorityPageCrawler(session=session, host_resolver=PUBLIC_RESOLVER)
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
        crawler = PriorityPageCrawler(session=session, host_resolver=PUBLIC_RESOLVER)

        records = crawler.crawl_lead({
            "domain": "example.com",
            "url": "https://example.com/",
        })

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["url"], "https://www.example.ca/en.html")

    def test_rejects_private_resolution_before_request(self):
        homepage = "https://internal.example/"
        session = FakeSession({homepage: FakeResponse(homepage, "<html>secret</html>")})
        crawler = PriorityPageCrawler(
            session=session, host_resolver=lambda hostname: ["127.0.0.1", "169.254.169.254"],
        )

        self.assertEqual(crawler.crawl_lead({"domain": "internal.example", "url": homepage}), [])
        self.assertEqual(session.requested, [])
        self.assertEqual(crawler.last_lead_report["attempts"][0]["outcome"], "UNSAFE_TARGET")

    def test_rejects_redirect_that_resolves_private(self):
        homepage = "https://example.com/"
        redirected = "http://127.0.0.1/admin"
        response = FakeResponse(homepage, status=302)
        response.headers["location"] = redirected
        session = FakeSession({homepage: response})
        crawler = PriorityPageCrawler(
            session=session,
            host_resolver=PUBLIC_RESOLVER,
        )

        self.assertEqual(crawler.crawl_lead({"domain": "example.com", "url": homepage}), [])
        self.assertEqual(session.requested, [(homepage, 15)])
        self.assertEqual(crawler.last_lead_report["attempts"][0]["outcome"], "UNSAFE_REDIRECT_TARGET")


if __name__ == "__main__":
    unittest.main()
