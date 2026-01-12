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
MAX_PAGES = 5

# Regex for phone numbers
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def scrape_google(query):
    """Scrape Google search results (Universal approach)."""
    results = []
    
    # URL Template (Removed &udm=1 to get standard stable results)
    BASE_URL = "https://www.google.com/search?q={q}&start={start}"
    
    # User-Agent
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        logger.info(f"Starting scrape for query: {query}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(headers)
            page.set_default_timeout(60000)

            for page_num in range(1, MAX_PAGES + 1):
                start = (page_num - 1) * 10
                current_url = BASE_URL.format(q=query, start=start)
                logger.info(f"Scraping page {page_num}/{MAX_PAGES} -> {current_url}")

                page.goto(current_url)
                page.wait_for_timeout(4000) 

                # 1. LOG PAGE TITLE (To check for Captcha)
                title = page.title()
                logger.info(f"Page Title: {title}") 
                
                if "unusual traffic" in title.lower() or "check you're not a robot" in title.lower() or "captcha" in title.lower():
                    logger.error("⚠️ Google blocked this IP.")
                    break

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # 2. TRY TWO SELECTORS
                # Selector A: The Visual Card (w7Dbne)
                items = soup.select("div.w7Dbne")
                
                # Selector B: Standard Search Result (div.g) - Fallback
                if not items:
                    items = soup.select("div.g")

                if not items:
                    logger.info(f"Page {page_num}: No items found with standard selectors.")
                    continue

                current_page_results = 0

                for item in items:
                    # Try to find Name
                    name_tag = item.select_one("span.OSrXXb") or item.select_one("h3") or item.select_one("h2")
                    name = name_tag.get_text(strip=True) if name_tag else "Unknown Name"
                    
                    phone = None
                    
                    # Scan entire item content for phone number
                    text = item.get_text(" ", strip=True)
                    match = PHONE_REGEX.search(text)
                    if match:
                        phone = match.group(1)

                    # Try to find Image
                    img_tag = item.select_one("img")
                    image_link = img_tag['src'] if img_tag else None

                    # Only save if we have a phone number AND a name
                    if phone and name != "Unknown Name":
                        entry = {"name": name, "phone": phone, "image": image_link}
                        if entry not in results:
                            results.append(entry)
                            current_page_results += 1
                            logger.info(f"Found: {name} - {phone}")
                        else:
                            logger.info(f"Duplicate skipped: {name} - {phone}")

                logger.info(f"Finished page {page_num}. Added {current_page_results} new results.")
                time.sleep(2)

    except Exception as e:
        logger.exception("Error during scraping")
    
    # Save JSON
    safe_name = re.sub(r'[^a-z0-9\-]+', '-', query.lower())
    now = datetime.now().strftime("%Y-%m-%d-%H-%M")
    filename = f"{safe_name}-{now}.json"
    
    filepath = os.path.join(DATA_DIR, filename)
    
    logger.info(f"Saving {len(results)} results to {filepath}")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results, filename

if __name__ == "__main__":
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "default query"
    logger.info(f"Received query: {query_arg}")
    scrape_google(query_arg)
    logger.info("Job finished.")
