import json
import os
import time
import pandas as pd
from src.config_loader import ConfigLoader
from src.scraper.browser import BrowserManager
from src.scraper.email_scraper import EmailScraper

class PipelineOrchestrator:
    def __init__(self):
        self.config_loader = ConfigLoader()
        self.browser_manager = BrowserManager()
        self.page = None
        self.email_scraper = None

    def run(self):
        # 1. Load Data
        print("📂 Loading data...")
        raw_path = self.config_loader.config.get("paths", {}).get("raw_data")
        if not os.path.exists(raw_path):
            print(f"❌ Error: Could not find data file at {raw_path}")
            return

        with open(raw_path, 'r') as f:
            data = json.load(f)

        # 2. Initialize Browser
        print("🚀 Starting browser...")
        self.page = self.browser_manager.start_browser()
        self.email_scraper = EmailScraper(self.page)
        
        # 3. Load or Initialize Progress
        processed_path = self.config_loader.config.get("paths", {}).get("processed_data")
        if os.path.exists(processed_path):
            with open(processed_path, 'r') as f:
                results = json.load(f)
            print(f"📋 Resuming... Already processed {len(results)} records.")
        else:
            results = []
            print("🆕 Starting fresh...")

        # 4. Loop through the data
        total = len(data)
        print(f"⚙️ Processing {total} records...")
        
        # Check if we have already processed all records
        if len(results) >= total:
            print("✅ All records already processed! Delete 'data/processed/progress_data.json' to run again.")
            self.browser_manager.close_browser()
            return

        # Loop through the remaining records
        for idx in range(len(results), total):
            business = data[idx]
            name = business.get('company', 'Unknown')
            website = business.get('website')

            print(f"[{idx+1}/{total}] {name}")

            if not website or website == "—":
                results.append({"company": name, "website": None, "email": None, "error": "No website"})
                continue

            try:
                # Construct URL if missing protocol
                if not website.startswith("http"):
                    website = "https://" + website

                self.page.goto(website, timeout=30000)
                
                # Try to find contact page first for better results
                # Wait a moment for page to load
                self.page.wait_for_load_state("domcontentloaded")
                
                contact_link = self.page.locator("xpath=//a[contains(translate(text(), 'CONTACT', 'contact'), 'contact')]").first
                if contact_link.is_visible(timeout=2000):
                    contact_link.click()
                    self.page.wait_for_load_state("domcontentloaded")

                email = self.email_scraper.extract_email()
                results.append({"company": name, "website": website, "email": email, "error": None})
                
                # Save progress every single record
                with open(processed_path, 'w') as f:
                    json.dump(results, f, indent=4)

            except Exception as e:
                print(f"   ❌ Error: {e}")
                results.append({"company": name, "website": website, "email": None, "error": str(e)})
                
                # Save progress even on error
                with open(processed_path, 'w') as f:
                    json.dump(results, f, indent=4)

            # Be polite to the servers (Add a delay between requests)
            time.sleep(2)

        # 5. Save Final Output
        print("💾 Saving final file...")
        output_path = self.config_loader.config.get("paths", {}).get("output_data")
        df = pd.DataFrame(results)
        df.to_excel(output_path, index=False)
        
        # 6. Close Browser
        self.browser_manager.close_browser()
        print("✅ Pipeline complete! Check data/output/ for your file.")

if __name__ == "__main__":
    pipeline = PipelineOrchestrator()
    pipeline.run()
