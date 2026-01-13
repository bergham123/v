import sys
import re
import json
import os
import time
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# --- Configuration ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DEBUG_DIR = os.path.join(DATA_DIR, "debug_html")
os.makedirs(DEBUG_DIR, exist_ok=True)

MAX_PAGES = 5

# Regex for phone numbers
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def check_for_block(soup, page_num):
    """
    Checks if the page returned is a CAPTCHA/Block page.
    Returns True if blocked, False otherwise.
    """
    # Convert to lowercase for easier searching
    page_text = soup.get_text(separator=" ", strip=True).lower()
    
    # Keywords found in your error message
    block_keywords = [
        "unusual traffic from your computer network",
        "checks to see if it's really you",
        "this page checks to see if it's really you sending the requests"
    ]
    
    if any(keyword in page_text for keyword in block_keywords):
        logger.error(f"🚨 BLOCK DETECTED on Page {page_num}: Google has flagged this IP.")
        logger.error(f"🚨 The script is stopping to save resources.")
        return True
    return False

def scrape_google(query):
    """Scrape Google search results with Block Detection."""
    results = []
    BASE_URL = "https://www.google.com/search?q={q}&hl=en&start={start}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        logger.info(f"Starting scrape for query: {query}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, 
                args=['--disable-blink-features=AutomationControlled']
            )
            page = browser.new_page()
            page.set_extra_http_headers(headers)
            page.set_default_timeout(60000)

            for page_num in range(1, MAX_PAGES + 1):
                start = (page_num - 1) * 10
                formatted_query = quote_plus(query)
                current_url = BASE_URL.format(q=formatted_query, start=start)
                
                logger.info(f"Scraping page {page_num}/{MAX_PAGES} -> {current_url}")

                page.goto(current_url, wait_until="domcontentloaded")
                
                # Wait for search container (will fail if blocked)
                try:
                    page.wait_for_selector("div#search", state="attached", timeout=15000)
                except:
                    logger.warning(f"Timeout waiting for content on page {page_num}. Checking for CAPTCHA...")

                # Save HTML for debugging
                html = page.content()
                debug_filename = os.path.join(DEBUG_DIR, f"page_{page_num}_debug.html")
                with open(debug_filename, "w", encoding="utf-8") as f:
                    f.write(html)

                soup = BeautifulSoup(html, "html.parser")

                # --- CHECK FOR BLOCK ---
                if check_for_block(soup, page_num):
                    # Stop the workflow immediately
                    return results, "blocked"

                # --- SELECTORS STRATEGY ---
                items = soup.select("div.w7Dbne") # Map Card
                if not items:
                    items = soup.select("div.g") # Organic

                if not items:
                    logger.info(f"Page {page_num}: No items found.")
                    time.sleep(2)
                    continue

                current_page_results = 0

                for item in items:
                    name_tag = item.select_one("span.OSrXXb") or item.select_one("h3")
                    name = name_tag.get_text(strip=True) if name_tag else "Unknown Name"
                    
                    if name == "Unknown Name" or len(name) < 3:
                        continue

                    phone = None
                    text = item.get_text(" ", strip=True)
                    match = PHONE_REGEX.search(text)
                    if match:
                        phone = match.group(1)

                    # Image
                    img_tag = item.select_one("img")
                    image_link = img_tag['src'] if img_tag else None

                    if phone:
                        entry = {"name": name, "phone": phone, "image": image_link}
                        if entry not in results:
                            results.append(entry)
                            current_page_results += 1
                            logger.info(f"Found: {name} - {phone}")

                logger.info(f"Finished page {page_num}. Added {current_page_results} results.")
                time.sleep(2)

            browser.close()

    except Exception as e:
        logger.exception("Critical Error")
    
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
    scrape_google(query_arg)
