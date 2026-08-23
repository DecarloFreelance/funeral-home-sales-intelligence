import unittest

from extraction.contact_extractor import extract_contact_intelligence


class ContactExtractorTests(unittest.TestCase):

    def test_extracts_text_contacts_and_adjacent_role(self):
        result = extract_contact_intelligence([
            {
                "url": "https://example.com/team",
                "text": (
                    "Our Team\n"
                    "Jane O'Connor\n"
                    "Licensed Funeral Director\n"
                    "Email info@example.com or call (780) 555-1234."
                ),
            }
        ], "example.com")

        self.assertEqual(result["emails"], ["info@example.com"])
        self.assertEqual(
            result["email_validation"][0]["deliverability"], "NOT_CHECKED"
        )
        self.assertEqual(result["email_validation"][0]["confidence"], 95)
        self.assertEqual(result["phones"], ["(780) 555-1234"])
        self.assertEqual(
            result["phone_verification"][0]["reachability"], "NOT_CHECKED"
        )
        self.assertEqual(result["people"][0]["name"], "Jane O'Connor")
        self.assertEqual(result["people"][0]["source"], "page_text")
        self.assertEqual(result["email_sources"], [{
            "value": "info@example.com", "source_url": "https://example.com/team",
            "source_type": "page_text",
        }])
        self.assertEqual(result["phone_sources"][0]["source_url"], "https://example.com/team")
        self.assertEqual(result["completeness_score"], 75)

    def test_extracts_business_person_and_address_from_json_ld(self):
        result = extract_contact_intelligence([
            {
                "url": "https://example.com/about",
                "text": "",
                "metadata": {
                    "jsonLd": [
                        {
                            "@type": "FuneralHome",
                            "name": "Example Funeral Home",
                            "telephone": "+1-403-555-1234",
                            "email": "care@example.com",
                            "address": {
                                "@type": "PostalAddress",
                                "streetAddress": "1 Main Street",
                                "addressLocality": "Calgary",
                                "addressRegion": "AB",
                                "postalCode": "T2P 1A1",
                                "addressCountry": "CA",
                            },
                        },
                        {
                            "@type": "Person",
                            "name": "John Smith",
                            "jobTitle": "Owner and Funeral Director",
                        },
                    ]
                },
            }
        ], "example.com")

        self.assertEqual(result["business_names"], ["Example Funeral Home"])
        self.assertEqual(result["addresses"][0]["city"], "Calgary")
        self.assertEqual(result["addresses"][0]["source_url"], "https://example.com/about")
        self.assertEqual(result["people"][0]["name"], "John Smith")
        self.assertEqual(result["people"][0]["source"], "schema.org")
        self.assertEqual(result["completeness_score"], 100)

    def test_extracts_json_ld_embedded_in_html_and_ignores_bad_json(self):
        html = """
        <script type="application/ld+json">not valid json</script>
        <script type="application/ld+json">
          {"@type":"LocalBusiness","name":"HTML Funeral Home",
           "telephone":"403.555.6789"}
        </script>
        """
        result = extract_contact_intelligence([
            {"url": "https://html.example", "text": "", "html": html}
        ], "html.example")

        self.assertEqual(result["business_names"], ["HTML Funeral Home"])
        self.assertEqual(result["phones"], ["403.555.6789"])

    def test_does_not_infer_people_from_generic_role_prose(self):
        result = extract_contact_intelligence([
            {
                "url": "https://example.com/resources",
                "text": (
                    "Making Arrangements\n"
                    "A funeral director can help families make arrangements.\n"
                    "Cremation Costs\n"
                    "Licensed Funeral Director"
                ),
            }
        ], "example.com")

        self.assertEqual(result["people"], [])

    def test_rejects_observed_hosted_form_placeholder_email(self):
        result = extract_contact_intelligence([{
            "url": "https://example.com/", "text": "Email info@example.com or filler@godaddy.com",
        }], "example.com")
        self.assertEqual(result["emails"], ["info@example.com"])

    def test_preserves_directory_contacts_and_branch_locations(self):
        result = extract_contact_intelligence([{
            "url": "https://example.com/",
            "text": "Example Funeral Home",
            "discovery": {
                "company": "Example Funeral Home",
                "contact_name": "Jane Smith",
                "contact_title": "Directory contact",
                "source_url": "https://directory.example/example",
                "email": "directory@example.com",
                "phone": "780-555-1234",
                "locations": [{
                    "company": "Example Funeral Home North",
                    "address": "1 Main Street",
                    "city": "Edmonton",
                    "province": "AB",
                    "country": "Canada",
                    "email": "north@example.com",
                    "phone": "780-555-5678",
                    "field_sources": {
                        "email": ["https://directory.example/north-email"],
                        "contact_name": ["https://directory.example/north-contact"],
                    },
                }],
            },
        }], "example.com")

        self.assertCountEqual(
            result["emails"],
            ["directory@example.com", "north@example.com"],
        )
        self.assertEqual(len(result["phones"]), 2)
        self.assertEqual(result["addresses"][0]["city"], "Edmonton")
        self.assertIn("Example Funeral Home North", result["business_names"])
        self.assertEqual(result["people"], [])
        self.assertEqual(result["directory_contacts"][0]["name"], "Jane Smith")
        self.assertEqual(
            result["directory_contacts"][0]["source_url"],
            "https://directory.example/example",
        )
        self.assertEqual(result["email_sources"][0]["source_url"], "https://directory.example/example")
        north = next(item for item in result["email_sources"] if item["value"] == "north@example.com")
        self.assertEqual(north["source_url"], "https://directory.example/north-email")


if __name__ == "__main__":
    unittest.main()
