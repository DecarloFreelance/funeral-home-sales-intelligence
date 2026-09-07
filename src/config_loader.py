import json
import os

class ConfigLoader:
    def __init__(self):
        # Get the root directory (two levels up from this file: src -> root)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config = self._load_json("config/config.json")
        self.provinces = self._load_json("config/provinces.json")
        
    def _load_json(self, path):
        full_path = os.path.join(self.base_dir, path)
        try:
            with open(full_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"❌ Error: Could not find {full_path}")
            return {}
        except json.JSONDecodeError as e:
            print(f"❌ Error: Syntax error in {full_path} - {e}")
            return {}

    def get_crm_config(self):
        return self.config.get("crm", {})
        
    def get_scraping_config(self):
        return self.config.get("scraping", {})

    def clean_province(self, raw_province):
        """Fixes scraped typos (e.g., MS -> NS) using the mapping file."""
        if not raw_province:
            return "Unknown"
        return self.provinces.get(raw_province.strip().upper(), raw_province.strip().upper())
