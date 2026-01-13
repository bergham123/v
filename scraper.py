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

# Create a specific folder to save HTML for debugging
DEBUG_DIR = os.path.join(DATA_DIR, "debug_html")
os.makedirs(DEBUG_DIR, exist_ok=True)

MAX_PAGES = 5

# Regex for phone numbers (Broadened slightly for different formats)
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def scrape_google(query):
    """Scrape Google search results with HTML saving for debugging."""
    results = []
    
    # URL Template: Added &hl=en to force English HTML structure
    BASE_URL = "https://www.google.com/search?q={q}&hl=en&start={start}"
    
    # User-Agent
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        logger.info(f"Starting scrape for query: {query}")
        
        with sync_playwright() as p:
            # Launch with anti-detection arguments
            browser = p.chromium.launch(
                headless=True, 
                args=['--disable-blink-features=AutomationControlled']
            )
            page = browser.new_page()
            page.set_extra_http_headers(headers)
            page.set_default_timeout(60000) # 60 seconds timeout

            for page_num in range(1, MAX_PAGES + 1):
                start = (page_num - 1) * 10
                
                # Format query (replace spaces with +)
                formatted_query = quote_plus(query)
                current_url = BASE_URL.format(q=formatted_query, start=start)
                
                logger.info(f"Scraping page {page_num}/{MAX_PAGES} -> {current_url}")

                # Go to URL and wait for network to be mostly idle
                page.goto(current_url, wait_until="domcontentloaded")
                
                # CRITICAL FIX: Wait specifically for the search container to load.
                # If this times out, Google likely detected the bot.
                try:
                    page.wait_for_selector("div#search", state="attached", timeout=15000)
                except Exception as e:
                    logger.warning(f"Timeout waiting for content selector on page {page_num}. Google might have blocked the request.")
                    # We continue anyway to download the HTML to see what happened.

                # DOWNLOAD PAGE: Save HTML for debugging
                html = page.content()
                debug_filename = os.path.join(DEBUG_DIR, f"page_{page_num}_debug.html")
                with open(debug_filename, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info(f"Saved HTML debug to {debug_filename}")

                soup = BeautifulSoup(html, "html.parser")

                # --- SELECTORS STRATEGY ---
                # 1. The Map/Local Pack (Visual Card)
                items = soup.select("div.w7Dbne")
                
                # 2. Standard Search Result (Organic)
                if not items:
                    items = soup.select("div.g")

                # 3. FALLBACK: If standard selectors fail, try finding any div with a specific data attribute 
                # often used in Google results or simply anchor tags
                if not items:
                    logger.info("Primary selectors failed. Attempting fallback...")
                    # Trying to find any 'a' tag that looks like a result link
                    items = soup.select("div[data-hveid]")

                if not items:
                    logger.info(f"Page {page_num}: No items found. Check the HTML file in 'data/debug_html'.")
                    time.sleep(2)
                    continue

                current_page_results = 0

                for item in items:
                    # Try to find Name (Multiple attempts)
                    name_tag = item.select_one("span.OSrXXb") or item.select_one("h3") or item.select_one("h2")
                    name = name_tag.get_text(strip=True) if name_tag else "Unknown Name"
                    
                    # Skip if name is too generic or empty
                    if name == "Unknown Name" or len(name) < 3:
                        continue

                    phone = None
                    
                    # Scan entire item content for phone number
                    text = item.get_text(" ", strip=True)
                    match = PHONE_REGEX.search(text)
                    if match:
                        phone = match.group(1)

                    # Try to find Image
                    img_tag = item.select_one("img")
                    image_link = img_tag['src'] if img_tag else None

                    # Only save if we have a phone number AND a valid name
                    if phone:
                        entry = {"name": name, "phone": phone, "image": image_link}
                        if entry not in results:
                            results.append(entry)
                            current_page_results += 1
                            logger.info(f"Found: {name} - {phone}")

                logger.info(f"Finished page {page_num}. Added {current_page_results} new results.")
                time.sleep(2)

            browser.close()

    except Exception as e:
        logger.exception("Critical Error during scraping")
    
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
    # Handle input safely
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "default query"
    logger.info(f"Received query: {query_arg}")
    scrape_google(query_arg)
    logger.info("Job finished.")
