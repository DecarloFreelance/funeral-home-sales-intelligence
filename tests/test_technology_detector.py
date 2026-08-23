import unittest

from technology_detector import detect_technology


class TechnologyDetectorTests(unittest.TestCase):
    def test_detects_real_public_html_signatures(self):
        result = detect_technology("""
            <script src="/wp-content/plugins/elementor/assets/app.js"></script>
            <script>var gforms_recaptcha_strings = {};</script>
            <script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC123"></script>
        """)
        self.assertEqual(
            set(result), {"WordPress", "Elementor", "Gravity Forms", "Google Tag Manager"}
        )
        self.assertTrue(all(item["confidence"] >= 0.9 for item in result.values()))

    def test_does_not_treat_marketing_prose_as_stack_evidence(self):
        self.assertEqual(
            detect_technology("We can build a WordPress site with forms and analytics."),
            {},
        )

    def test_detects_funeral_industry_site_provider_marker(self):
        result = detect_technology(
            '<img src="//s3.amazonaws.com/client-data.funeraltechweb.com/example/logo.png">'
        )
        self.assertEqual(set(result), {"FuneralTech"})


if __name__ == "__main__":
    unittest.main()
