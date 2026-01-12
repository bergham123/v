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
MAX_PAGES = 5

# Regex for phone numbers (improved)
PHONE_REGEX = re.compile(r'(?:(?:\+|00)\d{1,3}[\s\-]?)?(?:0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def scrape_google(query):
    """Scrape Google search results (Universal approach)."""
    results = []
    
    # URL Template with the new format
    # Note: Using quote_plus for proper URL encoding
    encoded_query = quote_plus(query)
    BASE_URL = f"https://www.google.com/search?q={encoded_query}&udm=1&start=" + "{start}"
    
    # User-Agent
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://www.google.com/",
    }

    try:
        logger.info(f"Starting scrape for query: {query}")
        logger.info(f"Using URL pattern: {BASE_URL}")
        
        with sync_playwright() as p:
            # Launch browser with additional arguments
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--window-size=1920,1080'
                ]
            )
            
            context = browser.new_context(
                user_agent=headers["User-Agent"],
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()
            page.set_extra_http_headers(headers)
            page.set_default_timeout(60000)

            for page_num in range(1, MAX_PAGES + 1):
                start = (page_num - 1) * 10
                current_url = BASE_URL.format(start=start)
                logger.info(f"Scraping page {page_num}/{MAX_PAGES} -> {current_url}")

                try:
                    response = page.goto(current_url, wait_until="networkidle")
                    if response.status != 200:
                        logger.warning(f"Page returned status {response.status}")
                        
                    # Wait for content to load
                    page.wait_for_load_state("domcontentloaded")
                    
                    # Check for captcha/block
                    if "sorry/index" in page.url or "check" in page.url:
                        logger.error("⚠️ Google blocked this IP (redirected to captcha).")
                        break
                    
                    # Additional check for captcha in content
                    captcha_selectors = [
                        "#captcha-form",
                        ".g-recaptcha",
                        "form[action*='sorry']",
                        "input[name='captcha']"
                    ]
                    
                    for selector in captcha_selectors:
                        if page.locator(selector).count() > 0:
                            logger.error("⚠️ Captcha detected.")
                            break

                    # 1. LOG PAGE TITLE (To check for Captcha)
                    title = page.title()
                    logger.info(f"Page Title: {title}") 
                    
                    if any(term in title.lower() for term in ["unusual traffic", "not a robot", "captcha", "sorry"]):
                        logger.error("⚠️ Google blocked this IP.")
                        break

                    html = page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # 2. TRY MULTIPLE SELECTORS for different Google result layouts
                    items = []
                    
                    # Selector 1: Common result container
                    items = soup.select("div.g, div.yuRUbf, div[data-sokoban-container], div.tF2Cxc")
                    
                    # Selector 2: Local business results
                    if not items:
                        items = soup.select("div.w7Dbne, div.VkpGBb, div.MUxGbd")
                    
                    # Selector 3: Universal results
                    if not items:
                        items = soup.select("div[class*=' ']")  # Fallback to any div with class
                        items = [item for item in items if len(item.get_text(strip=True)) > 50]

                    if not items:
                        logger.info(f"Page {page_num}: No items found with standard selectors.")
                        # Save screenshot for debugging
                        page.screenshot(path=f"debug_page_{page_num}.png")
                        continue

                    current_page_results = 0

                    for item in items:
                        # Try to find Name - multiple selectors
                        name = "Unknown Name"
                        name_selectors = [
                            "span.OSrXXb", "h3", "h2", "h3.LC20lb", 
                            "div.vk_bk", "span[role='heading']", "div.dBln1c"
                        ]
                        
                        for selector in name_selectors:
                            name_tag = item.select_one(selector)
                            if name_tag and name_tag.get_text(strip=True):
                                name = name_tag.get_text(strip=True)
                                break
                        
                        phone = None
                        
                        # Scan entire item content for phone number
                        text = item.get_text(" ", strip=True)
                        matches = PHONE_REGEX.findall(text)
                        if matches:
                            # Clean phone number
                            phone = matches[0]
                            phone = re.sub(r'[\s\-]+', '', phone)  # Remove spaces and dashes

                        # Try to find Image
                        image_link = None
                        img_selectors = ["img", "img.YQ4gaf", "img.XNo5Ab"]
                        for selector in img_selectors:
                            img_tag = item.select_one(selector)
                            if img_tag and img_tag.get('src'):
                                image_link = img_tag['src']
                                break

                        # Only save if we have a phone number AND a name
                        if phone and name != "Unknown Name":
                            entry = {
                                "name": name, 
                                "phone": phone, 
                                "image": image_link,
                                "query": query,
                                "page": page_num,
                                "timestamp": datetime.now().isoformat()
                            }
                            
                            # Check for duplicates more thoroughly
                            is_duplicate = False
                            for result in results:
                                if result['name'] == name and result['phone'] == phone:
                                    is_duplicate = True
                                    break
                            
                            if not is_duplicate:
                                results.append(entry)
                                current_page_results += 1
                                logger.info(f"Found: {name} - {phone}")
                            else:
                                logger.debug(f"Duplicate skipped: {name} - {phone}")

                    logger.info(f"Finished page {page_num}. Added {current_page_results} new results.")
                    
                    # Random delay between pages to avoid detection
                    time.sleep(2 + (page_num * 0.5))
                    
                except Exception as e:
                    logger.error(f"Error on page {page_num}: {str(e)}")
                    continue

            browser.close()

    except Exception as e:
        logger.exception(f"Error during scraping: {str(e)}")
    
    # Save JSON
    safe_name = re.sub(r'[^a-z0-9\-]+', '-', query.lower())
    now = datetime.now().strftime("%Y-%m-%d-%H-%M")
    filename = f"{safe_name}-{now}.json"
    
    filepath = os.path.join(DATA_DIR, filename)
    
    logger.info(f"Saving {len(results)} results to {filepath}")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "total_results": len(results),
            "results": results
        }, f, ensure_ascii=False, indent=2)

    return results, filename

if __name__ == "__main__":
    query_arg = sys.argv[1] if len(sys.argv) > 1 else "default query"
    logger.info(f"Received query: {query_arg}")
    
    try:
        results, filename = scrape_google(query_arg)
        logger.info(f"Job finished. Total results: {len(results)}")
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)
