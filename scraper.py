import sys
import re
import json
import os
import time
import logging
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# --- Configuration ---
DATA_DIR = "data"
# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Regex for phone numbers
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def scrape_google(query, progress_callback=None):
    """Scrape Google search results for a query."""
    results = []
    start = 0
    page_num = 1
    # Use the specific URL structure you provided
    BASE_URL = f"https://www.google.com/search?q={query.replace(' ','+')}&udm=1&start={start}"
    
    browser = None
    try:
        logger.info(f"Starting scrape for query: {query}")
        with sync_playwright() as p:
            # Run headless in GitHub Actions
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(60000)

            while True:
                # Construct URL for current page
                current_url = BASE_URL.format(start=start)
                logger.info(f"Scraping page {page_num} -> {current_url}")

                page.goto(current_url)
                # Wait for network idle or specific time
                page.wait_for_timeout(4000) 

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Select items based on your provided class
                items = soup.select("div.w7Dbne")
                if not items:
                    logger.info("No more items found, stopping pagination.")
                    break

                for item in items:
                    name_tag = item.select_one("span.OSrXXb")
                    if not name_tag:
                        continue
                    
                    name = name_tag.get_text(strip=True)
                    phone = None
                    
                    # Find phone number
                    for div in item.find_all("div"):
                        text = div.get_text(" ", strip=True)
                        match = PHONE_REGEX.search(text)
                        if match:
                            phone = match.group(1)
                            break

                    # Find image
                    img_tag = item.select_one("img")
                    image_link = img_tag['src'] if img_tag else None

                    if phone:
                        entry = {"name": name, "phone": phone, "image": image_link}
                        # Avoid duplicates in this session
                        if entry not in results:
                            results.append(entry)
                            logger.info(f"Found: {name} - {phone}")

                page_num += 1
                start += 10
                time.sleep(2)

    except Exception as e:
        logger.exception("Error while scraping Google")
    finally:
        if browser:
            browser.close()

    # Save JSON
    # Sanitize filename
    safe_name = re.sub(r'[^a-z0-9\-]+', '-', query.lower())
    filename = f"{safe_name.strip('-')}.json"
    filepath = os.path.join(DATA_DIR, filename)
    
    logger.info(f"Saving {len(results)} results to {filepath}")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results, filename

# ----------------- Main Execution -----------------
if __name__ == "__main__":
    # 1. Get argument from GitHub Workflow
    # If no argument provided, use a default
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "default query"
    
    logger.info(f"Received query: {query_arg}")
    
    # 2. Run scraper
    scrape_google(query_arg)
    
    logger.info("Job finished.")
