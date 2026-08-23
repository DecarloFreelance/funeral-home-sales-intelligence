import unittest

from intelligence.package_buyer_fit import rank_package_buyers, score_package_buyer


class PackageBuyerFitTests(unittest.TestCase):

    def test_independent_high_gap_business_is_direct_purchase_candidate(self):
        candidate = score_package_buyer({
            "domain": "independent.example",
            "digital_opportunity_score": 90,
            "contact_quality_score": 80,
            "sales_readiness": 80,
            "revenue_opportunity_score": 70,
            "missing": ["chat", "lead_capture", "online_planner", "pricing"],
            "business_profile": {"company": "Independent", "locations": [{}]},
            "contact_intelligence": {"people": []},
        })

        self.assertEqual(candidate["recommended_motion"], "DIRECT_PURCHASE")
        self.assertGreater(candidate["buyer_fit_score"], 80)

    def test_multilocation_operator_has_license_value(self):
        candidate = score_package_buyer({
            "domain": "group.example",
            "digital_opportunity_score": 70,
            "contact_quality_score": 70,
            "sales_readiness": 40,
            "revenue_opportunity_score": 80,
            "business_profile": {"locations": [{}, {}, {}, {}]},
            "contact_intelligence": {"people": [{"name": "Jane Smith"}]},
        })

        self.assertEqual(candidate["recommended_motion"], "LICENSE")

    def test_ranker_orders_highest_fit_first(self):
        rows = rank_package_buyers([
            {"domain": "low.example", "business_profile": {}, "contact_intelligence": {}},
            {
                "domain": "high.example", "digital_opportunity_score": 100,
                "contact_quality_score": 100, "sales_readiness": 100,
                "missing": ["chat", "lead_capture", "online_planner"],
                "business_profile": {}, "contact_intelligence": {},
            },
        ])

        self.assertEqual(rows[0]["domain"], "high.example")


if __name__ == "__main__":
    unittest.main()
