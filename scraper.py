import sys
import re
import json
import os
import time
import logging
import html
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# --- Configuration ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DEBUG_DIR = os.path.join(DATA_DIR, "debug_html")
os.makedirs(DEBUG_DIR, exist_ok=True)

# Set your target number of results here
TARGET_RESULTS = 100 
MAX_SCROLL_ITERATIONS = 30  # Safety limit (prevents infinite loop)

# Regex for phone numbers
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def extract_location_data(item):
    """Extracts data from a Bing Map List Item."""
    data = {
        "name": None,
        "phone": None,
        "image": None,
        "latitude": None,
        "longitude": None
    }

    name_tag = item.select_one("h3.l_magTitle")
    if name_tag:
        data["name"] = name_tag.get_text(strip=True)

    phone_tag = item.select_one("span.longNum")
    if phone_tag:
        data["phone"] = phone_tag.get_text(strip=True)

    img_tag = item.select_one("img")
    if img_tag:
        src = img_tag.get("src")
        if src:
            if src.startswith("//"):
                src = "https:" + src
            data["image"] = src

    card_div = item.select_one("div.b_maglistcard")
    if card_div and card_div.has_attr("data-entity"):
        raw_json = card_div["data-entity"]
        try:
            decoded_json = html.unescape(raw_json)
            entity_data = json.loads(decoded_json)
            geometry = entity_data.get("geometry", {})
            if not geometry:
                geometry = entity_data.get("routablePoint", {})
            data["latitude"] = geometry.get("y")
            data["longitude"] = geometry.get("x")
        except Exception as e:
            logger.debug(f"Could not parse location JSON: {e}")

    return data

def parse_combined_input(raw_input):
    """
    Splits a string like "hotel&cp=34.00~-6.00" into query and parameters.
    """
    parts = raw_input.split('&')
    query = parts[0]
    cp = None
    mb = None
    
    for part in parts[1:]:
        if part.startswith('cp='):
            cp = part.split('=', 1)[1]
        elif part.startswith('mb='):
            mb = part.split('=', 1)[1]
            
    return query, cp, mb

def scrape_bing_maps(raw_input):
    """
    Main scraper function.
    """
    query, cp, mb = parse_combined_input(raw_input)
    
    results = []
    BASE_URL = "https://www.bing.com/maps/search"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        logger.info(f"Parsed Query: {query}")
        if cp: logger.info(f"Using CP: {cp}")
        if mb: logger.info(f"Using MB: {mb}")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, 
                args=['--disable-blink-features=AutomationControlled']
            )
            page = browser.new_page()
            page.set_extra_http_headers(headers)
            page.set_default_timeout(60000)

            # --- URL CONSTRUCTION ---
            formatted_query = quote_plus(query)
            params = [f"q={formatted_query}", "style=r"]
            
            if cp:
                params.append(f"cp={cp}")
            if mb:
                params.append(f"mb={mb}")
            
            full_url = f"{BASE_URL}?{'&'.join(params)}"
            logger.info(f"Navigating to: {full_url}")

            page.goto(full_url, wait_until="domcontentloaded")

            # Wait for initial results
            try:
                page.wait_for_selector("li.listingItem_fPE1q", state="attached", timeout=15000)
            except:
                logger.warning("Timeout waiting for initial results.")
                # Return empty results so workflow doesn't crash, just saves empty file
                return [], "no_results"

            logger.info("Starting scroll to get " + str(TARGET_RESULTS) + " results...")
            
            scroll_iterations = 0
            same_count_iterations = 0

            # SCROLL LOOP - Stop when we have enough results
            while len(results) < TARGET_RESULTS and scroll_iterations < MAX_SCROLL_ITERATIONS:
                
                # Parse current page state
                html_content = page.content()
                soup = BeautifulSoup(html_content, "html.parser")
                items = soup.select("li.listingItem_fPE1q")
                
                # Extract new items
                current_results_count = len(items)
                new_items_found = False
                
                for item in items:
                    entry = extract_location_data(item)
                    # Check for duplicates based on name and phone
                    if entry["name"] and entry["phone"]:
                        # Simple duplicate check (optional, but good for quality)
                        if not any(d['name'] == entry['name'] and d['phone'] == entry['phone'] for d in results):
                            results.append(entry)
                            new_items_found = True

                # Feedback
                if scroll_iterations % 3 == 0:
                    logger.info(f"Scroll {scroll_iterations}: Found {len(results)} results so far...")

                # Check if we hit the target
                if len(results) >= TARGET_RESULTS:
                    logger.info(f"Target reached: {len(results)} results.")
                    break

                # Scroll logic
                # Check if content is stable (end of list)
                if not new_items_found:
                    same_count_iterations += 1
                else:
                    same_count_iterations = 0

                # If scrolled 3 times without new items, stop
                if same_count_iterations >= 3:
                    logger.info("End of list reached.")
                    break

                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except:
                    pass
                
                # Wait for data to load (randomized slightly to look human)
                time.sleep(1.5) 
                scroll_iterations += 1

            # Final Parse (in case we missed some during loop)
            html_content = page.content()
            soup = BeautifulSoup(html_content, "html.parser")
            items = soup.select("li.listingItem_fPE1q")
            
            for item in items:
                entry = extract_location_data(item)
                if entry["name"] and entry["phone"]:
                     if not any(d['name'] == entry['name'] and d['phone'] == entry['phone'] for d in results):
                        results.append(entry)
            
            # Limit exactly to TARGET_RESULTS if we got more
            results = results[:TARGET_RESULTS]

            browser.close()

    except Exception as e:
        logger.exception("Critical Error")
    
    # Save JSON
    safe_name = re.sub(r'[^a-z0-9\-]+', '-', query.lower())
    now = datetime.now().strftime("%Y-%m-%d-%H-%M")
    filename = f"{safe_name}-maps-{now}.json"
    filepath = os.path.join(DATA_DIR, filename)
    
    logger.info(f"Finished. Found {len(results)} results. Saving to {filepath}")
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results, filename

if __name__ == "__main__":
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "restaurant"
    scrape_bing_maps(query_arg)
