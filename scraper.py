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
from urllib.parse import quote_plus, urljoin

# --- Configuration ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DEBUG_DIR = os.path.join(DATA_DIR, "debug_html")
os.makedirs(DEBUG_DIR, exist_ok=True)

MAX_SCROLL_ITERATIONS = 20 

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
    
    # Loop through remaining parts to find cp or mb
    for part in parts[1:]:
        if part.startswith('cp='):
            cp = part.split('=', 1)[1]
        elif part.startswith('mb='):
            mb = part.split('=', 1)[1]
            
    return query, cp, mb

def scrape_bing_maps(raw_input):
    """
    Main scraper function accepting a combined string.
    """
    # 1. Parse the input to get Query, CP, and MB
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

            # --- SCROLLING ---
            logger.info("Waiting for initial results...")
            try:
                page.wait_for_selector("li.listingItem_fPE1q", state="attached", timeout=15000)
            except:
                logger.warning("Timeout waiting for initial results. Saving debug HTML.")
                with open(os.path.join(DEBUG_DIR, "initial_debug.html"), "w") as f:
                    f.write(page.content())
                return [], "no_results"

            logger.info("Starting scroll...")
            scroll_iterations = 0
            items_loaded_count = 0
            same_count_iterations = 0

            while scroll_iterations < MAX_SCROLL_ITERATIONS:
                current_items = page.locator("li.listingItem_fPE1q").count()
                if current_items > items_loaded_count:
                    logger.info(f"Scroll {scroll_iterations}: Loaded {current_items} items.")
                    items_loaded_count = current_items
                    same_count_iterations = 0
                else:
                    same_count_iterations += 1
                
                if same_count_iterations >= 3:
                    logger.info("Reached end of results.")
                    break

                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except:
                    pass
                time.sleep(2) 
                scroll_iterations += 1

            # --- PARSING ---
            logger.info("Parsing HTML...")
            html_content = page.content()
            debug_filename = os.path.join(DEBUG_DIR, "bing_maps_final.html")
            with open(debug_filename, "w", encoding="utf-8") as f:
                f.write(html_content)

            soup = BeautifulSoup(html_content, "html.parser")
            items = soup.select("li.listingItem_fPE1q")
            logger.info(f"Found {len(items)} items to process.")

            for item in items:
                entry = extract_location_data(item)
                if entry["name"] and entry["phone"]:
                    if entry not in results:
                        results.append(entry)
                        logger.info(f"✅ {entry['name']} | {entry['phone']}")

            browser.close()

    except Exception as e:
        logger.exception("Critical Error")
    
    # Save JSON
    safe_name = re.sub(r'[^a-z0-9\-]+', '-', query.lower())
    now = datetime.now().strftime("%Y-%m-%d-%H-%M")
    filename = f"{safe_name}-maps-{now}.json"
    filepath = os.path.join(DATA_DIR, filename)
    
    logger.info(f"Saving {len(results)} results to {filepath}")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results, filename

if __name__ == "__main__":
    # Only takes one argument now
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "restaurant"
    scrape_bing_maps(query_arg)
    logger.info("Job finished.")
