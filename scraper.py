import sys
import re
import json
import os
import time
import logging
import html  # Needed to decode the HTML entity JSON
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

# --- Configuration ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DEBUG_DIR = os.path.join(DATA_DIR, "debug_html")
os.makedirs(DEBUG_DIR, exist_ok=True)

MAX_PAGES = 5 # For Bing Maps, this will act as "Max Scroll Iterations"

# Regex for phone numbers (Broad)
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def extract_location_data(item):
    """
    Extracts data from a Bing Map List Item.
    Parses the hidden 'data-entity' JSON to get Lat/Lon.
    """
    data = {
        "name": None,
        "phone": None,
        "image": None,
        "latitude": None,
        "longitude": None
    }

    # 1. Name (h3.l_magTitle)
    name_tag = item.select_one("h3.l_magTitle")
    if name_tag:
        data["name"] = name_tag.get_text(strip=True)

    # 2. Phone (span.longNum)
    # We prioritize the HTML display over the JSON for phone, to ensure it's visible
    phone_tag = item.select_one("span.longNum")
    if phone_tag:
        data["phone"] = phone_tag.get_text(strip=True)

    # 3. Image (img tag)
    img_tag = item.select_one("img")
    if img_tag:
        src = img_tag.get("src")
        if src:
            # Handle protocol relative URLs (//th.bing.com)
            if src.startswith("//"):
                src = "https:" + src
            data["image"] = src

    # 4. Lat/Lon (Parse JSON data-entity)
    # The data-entity attribute contains the full details
    card_div = item.select_one("div.b_maglistcard")
    if card_div and card_div.has_attr("data-entity"):
        raw_json = card_div["data-entity"]
        try:
            # Decode HTML entities like &quot; -> "
            decoded_json = html.unescape(raw_json)
            entity_data = json.loads(decoded_json)
            
            # Get geometry
            # In Bing JSON: x = Longitude, y = Latitude
            geometry = entity_data.get("geometry", {})
            if not geometry:
                geometry = entity_data.get("routablePoint", {})
            
            data["latitude"] = geometry.get("y")
            data["longitude"] = geometry.get("x")

        except Exception as e:
            logger.debug(f"Could not parse location JSON for {data.get('name')}: {e}")

    return data

def scrape_bing_maps(query):
    """Scrape Bing Maps using Infinite Scroll."""
    results = []
    
    # URL Template for Bing Maps
    BASE_URL = "https://www.bing.com/maps?q={q}&FORM=HDRSC4"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        logger.info(f"Starting Bing Maps scrape for query: {query}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, 
                args=['--disable-blink-features=AutomationControlled']
            )
            page = browser.new_page()
            page.set_extra_http_headers(headers)
            page.set_default_timeout(60000)

            formatted_query = quote_plus(query)
            current_url = BASE_URL.format(q=formatted_query)
            
            logger.info(f"Navigating to: {current_url}")
            page.goto(current_url, wait_until="domcontentloaded")

            # --- SCROLLING LOGIC ---
            # Bing Maps loads results in a list container. We need to scroll down 
            # to trigger the "Load More" mechanism.
            
            # Wait for the list items to appear
            logger.info("Waiting for initial results...")
            try:
                page.wait_for_selector("li.listingItem_fPE1q", state="attached", timeout=15000)
            except:
                logger.warning("Timeout waiting for initial results. Saving debug HTML.")
                with open(os.path.join(DEBUG_DIR, "initial_debug.html"), "w") as f:
                    f.write(page.content())
                return [], "no_results"

            logger.info("Starting scroll to load all items...")
            
            # Define the maximum amount of scrolling loops to prevent infinite loops
            scroll_iterations = 0
            max_iterations = 20 # How many times to scroll down
            items_loaded_count = 0
            same_count_iterations = 0

            while scroll_iterations < max_iterations:
                # Get current number of items
                current_items = page.locator("li.listingItem_fPE1q").count()
                
                if current_items > items_loaded_count:
                    logger.info(f"Scroll {scroll_iterations}: Loaded {current_items} items so far.")
                    items_loaded_count = current_items
                    same_count_iterations = 0 # Reset counter if we found new items
                else:
                    same_count_iterations += 1
                    logger.info(f"Scroll {scroll_iterations}: No new items found (Count: {current_items}). Waiting...")
                
                # If we scrolled 3 times and no new items appeared, we probably reached the end
                if same_count_iterations >= 3:
                    logger.info("Reached end of results (no new items loading).")
                    break

                # Perform the scroll
                # Strategy: Scroll to the bottom of the page or the last item
                try:
                    # Scroll the window to the very bottom
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except:
                    pass

                # Wait a bit for the items to appear
                time.sleep(2) 
                scroll_iterations += 1

            # --- PARSING LOGIC ---
            logger.info("Finished scrolling. Parsing HTML...")
            html = page.content()
            
            # Save final HTML for debugging
            debug_filename = os.path.join(DEBUG_DIR, "bing_maps_final.html")
            with open(debug_filename, "w", encoding="utf-8") as f:
                f.write(html)

            soup = BeautifulSoup(html, "html.parser")
            items = soup.select("li.listingItem_fPE1q")

            logger.info(f"Found {len(items)} items in HTML.")

            for item in items:
                entry = extract_location_data(item)
                
                # Only save if we have a name and a phone
                if entry["name"] and entry["phone"]:
                    if entry not in results:
                        results.append(entry)
                        logger.info(f"✅ Found: {entry['name']} | {entry['phone']} | Lat: {entry['latitude']}, Lon: {entry['longitude']}")
                elif entry["name"]:
                    # Log items without phones just to show they exist
                    pass 

            browser.close()

    except Exception as e:
        logger.exception("Critical Error during scraping")
    
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
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "default query"
    logger.info(f"Received query: {query_arg}")
    scrape_bing_maps(query_arg)
    logger.info("Job finished.")
