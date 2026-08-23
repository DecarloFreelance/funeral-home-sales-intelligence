import unittest

from audit_client_sites import audit_client_pages


class AuditClientSitesTests(unittest.TestCase):

    def test_attributes_preview_email_to_affected_site(self):
        report = audit_client_pages([{
            "url": "https://life.example/contact",
            "text": "good@life.example bad@life-example.preview-domain.com",
        }, {
            "url": "https://todd.example/",
            "text": "Todd",
        }])

        self.assertTrue(report["preview_domain_issue_confirmed"])
        self.assertEqual(report["affected_site"], "life.example")
        self.assertEqual(report["affected_urls"], ["https://life.example/contact"])


if __name__ == "__main__":
    unittest.main()
