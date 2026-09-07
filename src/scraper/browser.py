from playwright.sync_api import sync_playwright
from src.config_loader import ConfigLoader

class BrowserManager:
    def __init__(self):
        self.config_loader = ConfigLoader()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start_browser(self):
        # Start Playwright
        self.playwright = sync_playwright().start()
        
        # Launch Chromium (headless=True runs in background, False shows the window)
        headless = self.config_loader.get_scraping_config().get("headless", True)
        self.browser = self.playwright.chromium.launch(headless=headless)

        # Create a new context (like an incognito window)
        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Create the page object
        self.page = self.context.new_page()
        
        return self.page

    def close_browser(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
