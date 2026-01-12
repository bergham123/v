import sys
import re
import json
import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# Configuration
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
MAX_PAGES = 5

# Phone regex
PHONE_REGEX = re.compile(r'(0\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})')

def scrape_google(query):
    """Simple Google scraper"""
    results = []
    
    # Format query for URL
    query_formatted = query.replace(' ', '+')
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            for page_num in range(1, MAX_PAGES + 1):
                start = (page_num - 1) * 10
                url = f"https://www.google.com/search?q={query_formatted}&udm=1&start={start}"
                
                print(f"Page {page_num}: {url}")
                
                page.goto(url)
                time.sleep(3)  # Wait for page to load
                
                html = page.content()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Find results
                items = soup.select("div.g, div.w7Dbne, div[data-sokoban-container]")
                
                for item in items:
                    # Get name
                    name_tag = item.select_one("h3, h2, span.OSrXXb")
                    name = name_tag.get_text(strip=True) if name_tag else ""
                    
                    # Get phone
                    text = item.get_text(" ", strip=True)
                    match = PHONE_REGEX.search(text)
                    phone = match.group(1) if match else None
                    
                    # Get image
                    img_tag = item.select_one("img")
                    image = img_tag['src'] if img_tag else None
                    
                    # Save if we have both name and phone
                    if name and phone and name != "Unknown Name":
                        results.append({
                            "name": name,
                            "phone": phone,
                            "image": image
                        })
                        print(f"Found: {name} - {phone}")
                
                time.sleep(2)  # Wait between pages
            
            browser.close()
    
    except Exception as e:
        print(f"Error: {e}")
    
    # Save results
    if results:
        safe_name = re.sub(r'[^a-z0-9]+', '-', query.lower())
        filename = f"{safe_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        filepath = os.path.join(DATA_DIR, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        
        print(f"Saved {len(results)} results to {filename}")
    
    return results

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "restaurant rabat"
    print(f"Searching for: {query}")
    scrape_google(query)
