import unittest

from src.agent import TOOLS, read_file, runtime_state


class ConstrainedAgentTests(unittest.TestCase):
    def test_agent_exposes_only_read_file(self):
        self.assertEqual([tool.name for tool in TOOLS], ["read_file"])
        self.assertIn("read_file", runtime_state()["available_tools"])
        self.assertTrue(read_file("src/agent.py"))

    def test_agent_rejects_paths_outside_repository(self):
        with self.assertRaises(ValueError):
            read_file("../README.md")


if __name__ == "__main__":
    unittest.main()