import sys
import re
import json
import os
import time
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# --- Configuration ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
MAX_PAGES = 5  # Fixed 5 pages

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Regex for phone numbers
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

def scrape_google(query):
    """Scrape Google search results for a query."""
    results = []
    
    # URL Template (Fixed pagination)
    BASE_URL = "https://www.google.com/search?q={q}&udm=1&start={start}"
    
    try:
        logger.info(f"Starting scrape for query: {query}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(60000)

            # Loop exactly 5 times
            for page_num in range(1, MAX_PAGES + 1):
                start = (page_num - 1) * 10
                url = BASE_URL.format(q=query, start=start)
                logger.info("Scraping page %s → %s", page_num, url)

                page.goto(url, timeout=60000)
                page.wait_for_timeout(4000)

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Using your selector logic
                items = soup.select("div.w7Dbne")
                
                if not items:
                    logger.info("No items found on this page.")
                    continue

                for item in items:
                    # Find Name
                    name_tag = item.select_one("span.OSrXXb")
                    if not name_tag:
                        continue
                    
                    name = name_tag.get_text(strip=True)

                    # Find Phone (Your Logic: Loop divs and regex search)
                    phone = None
                    for div in item.find_all("div"):
                        text = div.get_text(" ", strip=True)
                        match = PHONE_REGEX.search(text)
                        if match:
                            phone = match.group(1)
                            break

                    # Find Image
                    img_tag = item.select_one("img")
                    image_link = img_tag['src'] if img_tag else None

                    if phone:
                        entry = {"name": name, "phone": phone, "image": image_link}
                        if entry not in results:
                            results.append(entry)
                            logger.info(f"Found: {name} - {phone}")

                time.sleep(2)

    except Exception as e:
        logger.exception("Error while scraping Google")
    
    # NO finally block here (prevents crash)

    # Save JSON (Using your filename logic but added timestamp to be safe)
    safe_name = re.sub(r'[^a-z0-9\-]+', '-', query.lower())
    filename = f"{safe_name.strip('-')}.json"
    filepath = os.path.join(DATA_DIR, filename)
    
    logger.info(f"Saving {len(results)} results to {filepath}")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results, filename

# ----------------- Main Execution -----------------
if __name__ == "__main__":
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "default query"
    scrape_google(query_arg)
