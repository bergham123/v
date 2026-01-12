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

# Regex for phone numbers
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def scrape_google(query):
    """Scrape Google search results for a query."""
    results = []
    start = 0
    page_num = 1
    
    # URL Template
    BASE_URL = "https://www.google.com/search?q={q}&udm=1&start={start}"
    
    # We handle browser inside 'with', so we don't need a manual close.
    try:
        logger.info(f"Starting scrape for query: {query}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(60000)

            while True:
                # Construct URL
                current_url = BASE_URL.format(q=query, start=start)
                logger.info(f"Scraping page {page_num} -> {current_url}")

                page.goto(current_url)
                page.wait_for_timeout(4000) 

                # 1. Check for Google Block / Captcha
                title = page.title().lower()
                if "unusual traffic" in title or "check you're not a robot" in title or "captcha" in title:
                    logger.error("⚠️ Google blocked this IP (Unusual Traffic).")
                    # Save the HTML to verify
                    with open(os.path.join(DATA_DIR, "blocked_page.html"), "w") as f:
                        f.write(page.content())
                    break

                html = page.content()
                
                # 2. Parse with BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")

                # 3. Select Items (The selector might need updating if Google changes DOM)
                # Debug: Save first page HTML to see what we got
                if page_num == 1:
                    with open(os.path.join(DATA_DIR, "debug_page_1.html"), "w", encoding="utf-8") as f:
                        f.write(html)

                items = soup.select("div.w7Dbne")
                if not items:
                    logger.info("No more items found (or selectors changed). Stopping.")
                    break

                current_page_results = 0

                for item in items:
                    name_tag = item.select_one("span.OSrXXb")
                    if not name_tag:
                        continue
                    
                    name = name_tag.get_text(strip=True)
                    phone = None
                    
                    # Search for phone in divs
                    for div in item.find_all("div"):
                        text = div.get_text(" ", strip=True)
                        match = PHONE_REGEX.search(text)
                        if match:
                            phone = match.group(1)
                            break

                    img_tag = item.select_one("img")
                    image_link = img_tag['src'] if img_tag else None

                    if phone:
                        entry = {"name": name, "phone": phone, "image": image_link}
                        if entry not in results:
                            results.append(entry)
                            current_page_results += 1
                            logger.info(f"Found: {name} - {phone}")

                if current_page_results == 0:
                    # Log details before breaking
                    logger.info("No new unique results on this page. Stopping to avoid loop.")
                    logger.info(f"Total items found on page: {len(items)}")
                    break

                page_num += 1
                start += 10
                time.sleep(2)

    except Exception as e:
        logger.exception("Error during scraping")
    finally:
        # NO browser.close() here. 
        # The 'with sync_playwright()' context manager handles it automatically.
        pass

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
