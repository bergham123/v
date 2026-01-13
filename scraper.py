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

# Regex for phone numbers (Moroccan format generally, but works for others)
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def scrape_bing(query):
    """Scrape Bing search results."""
    results = []
    
    # URL Template: Added &setlang=en to force English HTML structure
    # Bing uses 'first' for pagination: Page 1 = 1, Page 2 = 11, Page 3 = 21
    BASE_URL = "https://www.bing.com/search?q={q}&setlang=en&first={start}"
    
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
            page.set_default_timeout(60000) 

            for page_num in range(1, MAX_PAGES + 1):
                # Calculate Bing Offset (Page 1 starts at 1, Page 2 at 11)
                start_index = (page_num - 1) * 10 + 1
                
                formatted_query = quote_plus(query)
                current_url = BASE_URL.format(q=formatted_query, start=start_index)
                
                logger.info(f"Scraping page {page_num}/{MAX_PAGES} -> {current_url}")

                page.goto(current_url, wait_until="domcontentloaded")
                
                # Wait specifically for Bing's result container
                try:
                    page.wait_for_selector("li.b_algo", state="attached", timeout=15000)
                except Exception as e:
                    logger.warning(f"Timeout waiting for content on page {page_num}. Saving debug HTML...")

                # DOWNLOAD PAGE: Save HTML for debugging
                html = page.content()
                debug_filename = os.path.join(DEBUG_DIR, f"bing_page_{page_num}_debug.html")
                with open(debug_filename, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info(f"Saved HTML debug to {debug_filename}")

                soup = BeautifulSoup(html, "html.parser")

                # --- SELECTORS STRATEGY FOR BING ---
                # 'li.b_algo' is the standard class for organic results in Bing
                items = soup.select("li.b_algo")

                if not items:
                    logger.info(f"Page {page_num}: No items found.")
                    time.sleep(2)
                    continue

                current_page_results = 0

                for item in items:
                    # Try to find Name (Bing uses h2 for the link title)
                    name_tag = item.select_one("h2")
                    name = name_tag.get_text(strip=True) if name_tag else None
                    
                    # Skip if no name
                    if not name:
                        continue
                    
                    # Filter out generic bing suggestions if necessary
                    if name.lower() in ["web", "images", "maps", "videos"]:
                        continue

                    phone = None
                    
                    # Scan entire item content for phone number
                    # Bing often puts phone numbers in the snippet (div class="b_caption")
                    text = item.get_text(" ", strip=True)
                    match = PHONE_REGEX.search(text)
                    if match:
                        phone = match.group(1)

                    # Try to find Image (Thumbnails in rich cards)
                    # Often located in a specific 'card' div or just any img tag inside
                    img_tag = item.select_one("img")
                    image_link = img_tag['src'] if img_tag else None

                    # Only save if we have a phone number
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
    filename = f"{safe_name}-bing-{now}.json" # Added 'bing' to filename to distinguish
    
    filepath = os.path.join(DATA_DIR, filename)
    
    logger.info(f"Saving {len(results)} results to {filepath}")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results, filename

if __name__ == "__main__":
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "default query"
    logger.info(f"Received query: {query_arg}")
    scrape_bing(query_arg)
    logger.info("Job finished.")
