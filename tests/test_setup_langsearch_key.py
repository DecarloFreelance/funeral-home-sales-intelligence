import unittest

from setup_langsearch_key import upsert_env_var


class UpsertEnvVarTests(unittest.TestCase):
    def test_appends_to_empty_file(self):
        result = upsert_env_var("", "LANGSEARCH_API_KEY", "abc123")
        self.assertEqual(result, "LANGSEARCH_API_KEY=abc123\n")

    def test_preserves_other_existing_vars_and_order(self):
        existing = "OPENAI_API_KEY=sk-1\nGROQ_API_KEY=gsk-1\n"
        result = upsert_env_var(existing, "LANGSEARCH_API_KEY", "abc123")
        self.assertEqual(
            result,
            "OPENAI_API_KEY=sk-1\nGROQ_API_KEY=gsk-1\nLANGSEARCH_API_KEY=abc123\n",
        )

    def test_replaces_existing_value_in_place(self):
        existing = "OPENAI_API_KEY=sk-1\nLANGSEARCH_API_KEY=old\nGROQ_API_KEY=gsk-1\n"
        result = upsert_env_var(existing, "LANGSEARCH_API_KEY", "new")
        self.assertEqual(
            result,
            "OPENAI_API_KEY=sk-1\nLANGSEARCH_API_KEY=new\nGROQ_API_KEY=gsk-1\n",
        )

    def test_does_not_false_match_a_longer_key_name(self):
        existing = "LANGSEARCH_API_KEY_BACKUP=keep-me\n"
        result = upsert_env_var(existing, "LANGSEARCH_API_KEY", "abc123")
        self.assertEqual(
            result,
            "LANGSEARCH_API_KEY_BACKUP=keep-me\nLANGSEARCH_API_KEY=abc123\n",
        )


if __name__ == "__main__":
    unittest.main()
