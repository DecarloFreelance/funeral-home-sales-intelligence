import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from website_crawler import crawl_queue


def report(domain, status="SUCCESS"):
    return {
        "domain": domain, "status": status, "attempts": [],
        "pages": int(status == "SUCCESS"), "duration_ms": 5,
    }


class InterruptingCrawler:
    def crawl_queue(self, leads, on_lead=None, checkpoint=None):
        lead = list(leads)[0]
        checkpoint([{"url": lead["url"], "discovery": {"queue_domain": lead["domain"]}}], report(lead["domain"]))
        raise KeyboardInterrupt


class CompletingCrawler:
    selected = []

    def crawl_queue(self, leads, on_lead=None, checkpoint=None):
        type(self).selected = [lead["domain"] for lead in leads]
        records = []
        reports = []
        for lead in leads:
            item = {"url": lead["url"], "discovery": {"queue_domain": lead["domain"]}}
            item_report = report(lead["domain"])
            checkpoint([item], item_report)
            records.append(item)
            reports.append(item_report)
        self.last_report = {"leads": reports}
        return records


class WebsiteCrawlerRecoveryTests(unittest.TestCase):
    def test_interruption_checkpoints_and_resume_skips_completed_domain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue, output, report_path = root / "queue.json", root / "pages.json", root / "report.json"
            queue.write_text(json.dumps([
                {"domain": "one.example", "url": "https://one.example/"},
                {"domain": "two.example", "url": "https://two.example/"},
            ]), encoding="utf-8")

            with patch("website_crawler.PriorityPageCrawler", return_value=InterruptingCrawler()):
                with self.assertRaises(KeyboardInterrupt):
                    crawl_queue(queue, output, append=True, report_path=report_path)
            self.assertEqual([item["domain"] for item in json.loads(report_path.read_text())["leads"]], ["one.example"])
            self.assertEqual(len(json.loads(output.read_text())), 1)

            with patch("website_crawler.PriorityPageCrawler", return_value=CompletingCrawler()):
                summary = crawl_queue(queue, output, append=True, resume=True, report_path=report_path)
            self.assertEqual(CompletingCrawler.selected, ["two.example"])
            self.assertEqual(len(json.loads(output.read_text())), 2)
            self.assertEqual(summary["queued_domains"], 2)
            self.assertEqual(summary["successful_domains"], 2)

    def test_append_keeps_shared_urls_separate_and_replaces_entity_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue, output = root / "queue.json", root / "pages.json"
            queue.write_text(json.dumps([
                {"domain": "one.example", "url": "https://network.example/location/1"},
                {"domain": "two.example", "url": "https://network.example/location/1"},
            ]), encoding="utf-8")
            output.write_text(json.dumps([
                {"url": "https://network.example/stale", "discovery": {"queue_domain": "one.example"}},
            ]), encoding="utf-8")

            with patch("website_crawler.PriorityPageCrawler", return_value=CompletingCrawler()):
                crawl_queue(queue, output, append=True)

            records = json.loads(output.read_text())
            self.assertEqual(len(records), 2)
            self.assertEqual(
                {item["discovery"]["queue_domain"] for item in records},
                {"one.example", "two.example"},
            )
            self.assertNotIn("https://network.example/stale", {item["url"] for item in records})


if __name__ == "__main__":
    unittest.main()
