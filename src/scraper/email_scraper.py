import re

class EmailScraper:
    def __init__(self, page):
        self.page = page

    def extract_email(self):
        """
        Aggressively looks for emails using multiple strategies.
        """
        email = None
        
        # --- Strategy 1: Click buttons to reveal emails ---
        try:
            button = self.page.locator("xpath=//button[contains(translate(text(), 'EMAIL', 'email'), 'email')] | //a[contains(text(), 'Show Email')]").first
            if button.is_visible(timeout=1500):
                button.click()
                self.page.wait_for_timeout(1000)
        except:
            pass

        # --- Strategy 2: Grab any 'mailto:' links in the DOM ---
        try:
            # Check if any anchor tags have mailto in them
            mailto_links = self.page.locator("a[href^='mailto:']")
            count = mailto_links.count()
            if count > 0:
                email = mailto_links.first.get_attribute("href").replace("mailto:", "").split("?")[0]
        except:
            pass

        # --- Strategy 3: Check specific HTML elements (Footer, Contact page) ---
        if not email:
            try:
                # Look for common elements that hold emails directly (e.g., <a>, <p>, <span>)
                # We limit to the body to avoid hidden scripts
                elements = self.page.locator("body a, body p, body span, body div").all()
                for element in elements:
                    try:
                        text = element.inner_text(timeout=500)
                        if "@" in text and "." in text:
                            # Simple regex to isolate the exact email string
                            match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
                            if match:
                                email = match.group(0)
                                break
                    except:
                        continue
            except:
                pass

        # --- Strategy 4: Regex on the raw HTML (catches obfuscated) ---
        if not email:
            try:
                html = self.page.content()
                obfuscated_patterns = [
                    r"[a-zA-Z0-9._%+-]+\[at\][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                    r"[a-zA-Z0-9._%+-]+\s*\(at\)\s*[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                    r"[a-zA-Z0-9._%+-]+\s@\s[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
                ]
                for pattern in obfuscated_patterns:
                    match = re.search(pattern, html)
                    if match:
                        email = match.group(0)
                        email = email.replace("[at]", "@").replace("(at)", "@").replace(" ", "")
                        break
            except:
                pass

        # Cleanup (remove trailing punctuation)
        if email:
            email = email.strip().strip('.,;:()[]')
            
        return email
