#!/usr/bin/env python3
"""
Google Business Scraper for GitHub Actions
Scrapes Google search results for businesses with phone numbers
"""

import sys
import re
import json
import os
import time
import logging
from datetime import datetime
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup

# --- Configuration ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
MAX_PAGES = int(os.environ.get('MAX_PAGES', '5'))

# Regex for phone numbers (improved for various formats)
PHONE_REGEX = re.compile(
    r'(?:'
    r'(?:\+|00)\d{1,3}[\s\-.]?'  # Country code
    r'|0\d[\s\-.]?'  # Local prefix
    r')'
    r'(?:[\s\-.]?\d{2,3}){4}'  # Main number parts
    r'|'  # OR
    r'0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}'  # French format
    r'|'  # OR
    r'\(\d{3}\)[\s\-]?\d{3}[\s\-]?\d{4}'  # US format
    r')'
)

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scraper.log')
    ]
)
logger = logging.getLogger(__name__)

def clean_phone_number(phone_str):
    """Clean and standardize phone number format"""
    if not phone_str:
        return None
    
    # Remove all non-digit characters except plus sign
    cleaned = re.sub(r'[^\d+]', '', phone_str)
    
    # If it starts with 00, replace with +
    if cleaned.startswith('00'):
        cleaned = '+' + cleaned[2:]
    
    # For French numbers without country code, ensure they start with 0
    if cleaned.startswith('33') and len(cleaned) == 11:
        cleaned = '0' + cleaned[2:]
    
    return cleaned

def setup_browser_context(playwright):
    """Setup browser with proper configuration"""
    chromium = playwright.chromium
    
    # Browser launch arguments for headless environments
    browser = chromium.launch(
        headless=True,
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--disable-gpu',
            '--window-size=1920,1080',
            '--disable-blink-features=AutomationControlled',
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ],
        timeout=60000
    )
    
    # Create context with viewport
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        locale='en-US',
        timezone_id='America/New_York'
    )
    
    # Block unnecessary resources to speed up
    context.route("**/*.{png,jpg,jpeg,gif,svg,ico}", lambda route: route.abort())
    context.route("**/*.css", lambda route: route.abort())
    context.route("**/*.woff", lambda route: route.abort())
    context.route("**/*.woff2", lambda route: route.abort())
    
    return browser, context

def is_captcha_page(page):
    """Check if we've been served a captcha page"""
    try:
        # Check URL
        if "sorry" in page.url or "check" in page.url:
            return True
        
        # Check title
        title = page.title().lower()
        captcha_indicators = [
            "captcha",
            "not a robot",
            "unusual traffic",
            "robot check",
            "verification"
        ]
        
        for indicator in captcha_indicators:
            if indicator in title:
                return True
        
        # Check for captcha elements
        captcha_selectors = [
            "#captcha-form",
            ".g-recaptcha",
            "form[action*='sorry']",
            "input[name='captcha']",
            "div.rc-"
        ]
        
        for selector in captcha_selectors:
            if page.locator(selector).count() > 0:
                return True
        
        # Check for "I'm not a robot" checkbox
        if page.locator("#recaptcha-anchor").count() > 0:
            return True
            
    except Exception:
        pass
    
    return False

def extract_business_info(item):
    """Extract business information from a search result item"""
    # Try multiple selectors for name
    name_selectors = [
        "span.OSrXXb",
        "h3.LC20lb",
        "h3",
        "h2",
        "div.vk_bk",
        "span[role='heading']",
        "div.dBln1c",
        "div.CNf3nf",
        "div.cXedhc"
    ]
    
    name = None
    for selector in name_selectors:
        name_tag = item.select_one(selector)
        if name_tag and name_tag.get_text(strip=True):
            name = name_tag.get_text(strip=True)
            break
    
    if not name or len(name) < 2:
        return None
    
    # Extract phone number
    phone = None
    text_content = item.get_text(" ", strip=True)
    
    # Look for phone numbers
    phone_matches = PHONE_REGEX.findall(text_content)
    if phone_matches:
        # Take the first valid phone number
        for match in phone_matches:
            cleaned_phone = clean_phone_number(match)
            if cleaned_phone and 8 <= len(cleaned_phone) <= 15:
                phone = cleaned_phone
                break
    
    # Try to find address/contact info section
    if not phone:
        contact_sections = item.select("div.rllt__details, div.s, div.I6TXqe, span.OSrXXb")
        for section in contact_sections:
            section_text = section.get_text(" ", strip=True)
            phone_matches = PHONE_REGEX.findall(section_text)
            if phone_matches:
                for match in phone_matches:
                    cleaned_phone = clean_phone_number(match)
                    if cleaned_phone and 8 <= len(cleaned_phone) <= 15:
                        phone = cleaned_phone
                        break
                if phone:
                    break
    
    # Extract image
    image_link = None
    img_selectors = ["img.YQ4gaf", "img.XNo5Ab", "img", "img.rISBZc"]
    
    for selector in img_selectors:
        img_tag = item.select_one(selector)
        if img_tag:
            image_link = img_tag.get('src') or img_tag.get('data-src')
            if image_link and image_link.startswith('http'):
                break
            elif image_link and image_link.startswith('data:image'):
                # Handle base64 encoded images
                pass
    
    # Extract rating if available
    rating = None
    rating_tag = item.select_one("span.rtng")
    if rating_tag:
        rating_text = rating_tag.get_text(strip=True)
        try:
            rating = float(re.search(r'[\d.]+', rating_text).group())
        except:
            pass
    
    # Extract reviews count if available
    reviews = None
    reviews_tag = item.select_one("span[aria-label*='review']")
    if reviews_tag:
        reviews_text = reviews_tag.get_text(strip=True)
        try:
            reviews = int(re.sub(r'[^\d]', '', reviews_text))
        except:
            pass
    
    # Extract category/type if available
    category = None
    category_tag = item.select_one("div.YhemCb, div.yuRUbf, div.CCgQ5")
    if category_tag:
        category = category_tag.get_text(strip=True)
    
    return {
        "name": name,
        "phone": phone,
        "image": image_link,
        "rating": rating,
        "reviews": reviews,
        "category": category
    }

def scrape_google(query):
    """Scrape Google search results for business information"""
    results = []
    successful_pages = 0
    
    # Validate and clean query
    query = query.strip()
    if not query:
        logger.error("Empty query provided")
        return results, None
    
    logger.info(f"Starting scrape for query: '{query}'")
    
    # Prepare query for URL
    try:
        encoded_query = quote_plus(query)
    except Exception as e:
        logger.error(f"Error encoding query: {e}")
        encoded_query = query.replace(' ', '+')
    
    # URL Template
    BASE_URL = f"https://www.google.com/search?q={encoded_query}&udm=1&start=" + "{start}"
    logger.info(f"Using URL pattern: {BASE_URL}")
    
    try:
        with sync_playwright() as p:
            browser, context = setup_browser_context(p)
            page = context.new_page()
            
            # Set additional headers
            page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Referer": "https://www.google.com/",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1"
            })
            
            page.set_default_timeout(45000)
            
            for page_num in range(MAX_PAGES):
                start = page_num * 10
                current_url = BASE_URL.format(start=start)
                logger.info(f"Scraping page {page_num + 1}/{MAX_PAGES} (start={start})")
                
                try:
                    # Navigate to page
                    response = page.goto(current_url, wait_until="networkidle", timeout=45000)
                    
                    if response and response.status != 200:
                        logger.warning(f"HTTP {response.status} for page {page_num + 1}")
                    
                    # Check for captcha
                    if is_captcha_page(page):
                        logger.error("CAPTCHA detected. Stopping scrape.")
                        page.screenshot(path=os.path.join(DATA_DIR, f"captcha_page_{page_num + 1}.png"))
                        break
                    
                    # Wait a bit for content to load
                    page.wait_for_timeout(3000)
                    
                    # Get page content
                    html = page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Find result items using multiple selectors
                    items = []
                    
                    # Try different selectors for different result types
                    selectors_to_try = [
                        "div.g",  # Standard results
                        "div[data-sokoban-container]",  # New layout
                        "div.w7Dbne",  # Business listings
                        "div.VkpGBb",  # Local results
                        "div.MUxGbd",  # Alternative
                        "div.tF2Cxc",  # Search results
                        "div.yuRUbf",  # Result container
                    ]
                    
                    for selector in selectors_to_try:
                        found_items = soup.select(selector)
                        if found_items:
                            items.extend(found_items)
                    
                    # Remove duplicates while preserving order
                    seen = set()
                    unique_items = []
                    for item in items:
                        item_hash = hash(str(item))
                        if item_hash not in seen:
                            seen.add(item_hash)
                            unique_items.append(item)
                    
                    logger.info(f"Found {len(unique_items)} unique result items on page {page_num + 1}")
                    
                    if not unique_items:
                        logger.warning(f"No result items found on page {page_num + 1}")
                        # Save screenshot for debugging
                        screenshot_path = os.path.join(DATA_DIR, f"debug_page_{page_num + 1}.png")
                        page.screenshot(path=screenshot_path)
                        logger.info(f"Saved screenshot to {screenshot_path}")
                        continue
                    
                    page_results = 0
                    
                    for item in unique_items:
                        try:
                            business_info = extract_business_info(item)
                            
                            if business_info and business_info.get('phone') and business_info.get('name'):
                                # Check for duplicates
                                is_duplicate = False
                                for existing in results:
                                    if (existing['name'] == business_info['name'] and 
                                        existing['phone'] == business_info['phone']):
                                        is_duplicate = True
                                        break
                                
                                if not is_duplicate:
                                    business_info.update({
                                        "query": query,
                                        "page": page_num + 1,
                                        "timestamp": datetime.now().isoformat()
                                    })
                                    results.append(business_info)
                                    page_results += 1
                                    logger.info(f"✓ Found: {business_info['name']} - {business_info['phone']}")
                                else:
                                    logger.debug(f"Duplicate: {business_info['name']}")
                        except Exception as e:
                            logger.debug(f"Error processing item: {e}")
                            continue
                    
                    logger.info(f"Page {page_num + 1}: Added {page_results} new results")
                    successful_pages += 1
                    
                    # Random delay between pages to avoid rate limiting
                    delay = 3 + (page_num * 0.5)
                    time.sleep(delay)
                    
                except PlaywrightTimeoutError:
                    logger.error(f"Timeout on page {page_num + 1}")
                    continue
                except Exception as e:
                    logger.error(f"Error on page {page_num + 1}: {str(e)}")
                    continue
            
            # Close browser
            browser.close()
            
    except Exception as e:
        logger.exception(f"Fatal error during scraping: {str(e)}")
        return results, None
    
    logger.info(f"Scraping completed. Successfully scraped {successful_pages} pages. Total results: {len(results)}")
    
    # Save results to JSON file
    if results:
        safe_name = re.sub(r'[^a-z0-9\-]+', '-', query.lower())
        now = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        filename = f"{safe_name}-{now}.json"
        filepath = os.path.join(DATA_DIR, filename)
        
        # Create metadata
        output_data = {
            "metadata": {
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "total_pages_scraped": successful_pages,
                "total_results": len(results),
                "success": True
            },
            "results": results
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Results saved to: {filepath}")
            return results, filename
        except Exception as e:
            logger.error(f"Error saving results: {e}")
            # Try alternative filename
            alt_filename = f"results-{now}.json"
            alt_filepath = os.path.join(DATA_DIR, alt_filename)
            try:
                with open(alt_filepath, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, ensure_ascii=False, indent=2)
                logger.info(f"Results saved to: {alt_filepath}")
                return results, alt_filename
            except:
                return results, None
    else:
        logger.warning("No results to save")
        
        # Save empty results file for tracking
        safe_name = re.sub(r'[^a-z0-9\-]+', '-', query.lower())
        now = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        filename = f"{safe_name}-{now}-empty.json"
        filepath = os.path.join(DATA_DIR, filename)
        
        output_data = {
            "metadata": {
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "total_pages_scraped": successful_pages,
                "total_results": 0,
                "success": False,
                "error": "No results found"
            },
            "results": []
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Empty results saved to: {filepath}")
        except:
            pass
        
        return results, None

def main():
    """Main entry point"""
    logger.info("=" * 50)
    logger.info("Starting Google Business Scraper")
    logger.info("=" * 50)
    
    # Get query from command line arguments
    if len(sys.argv) > 1:
        query = ' '.join(sys.argv[1:])  # Join all arguments to handle spaces
    else:
        logger.error("No query provided. Usage: python scraper.py 'your search query'")
        sys.exit(1)
    
    # Additional environment variable checks
    if 'MAX_PAGES' in os.environ:
        try:
            global MAX_PAGES
            MAX_PAGES = int(os.environ['MAX_PAGES'])
            logger.info(f"Using MAX_PAGES from environment: {MAX_PAGES}")
        except ValueError:
            logger.warning(f"Invalid MAX_PAGES value: {os.environ['MAX_PAGES']}")
    
    # Run scraper
    start_time = time.time()
    results, filename = scrape_google(query)
    elapsed_time = time.time() - start_time
    
    # Summary
    logger.info("=" * 50)
    logger.info("Scraping Summary:")
    logger.info(f"Query: {query}")
    logger.info(f"Results found: {len(results)}")
    logger.info(f"Time taken: {elapsed_time:.2f} seconds")
    logger.info(f"Output file: {filename if filename else 'None'}")
    logger.info("=" * 50)
    
    # Exit with appropriate code
    if results:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
