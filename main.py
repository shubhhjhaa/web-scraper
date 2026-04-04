import asyncio
import argparse
import os
import subprocess
import sys
import random
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright
from scraper.logger import general_log
from scraper.network import fetch_page, BlockingError, browser_initializer
from scraper.parser import parse_data
from scraper.cleaner import clean_and_validate, clean_business_profile
from scraper.storage import cache_html, save_to_csv, save_to_txt, save_to_json, save_to_excel


def detect_mode(url: str) -> str:
    """Auto-detects if URL is a listing page or a single business profile."""
    path = urlparse(url).path.lower()
    if "/find/" in path:
        return "listing"
    if "/connect/" in path or "/tradie/" in path:
        return "profile"
    if path.count("/") >= 2 and not any(x in path for x in ["search", "category", "shop", "browse"]):
        return "profile"
    return "listing"


BANNER = """
╔══════════════════════════════════════════════════════════════╗
║              ADVANCED STEALTH WEB SCRAPER                   ║
║          Playwright-Powered · Anti-Detection Engine         ║
╚══════════════════════════════════════════════════════════════╝
"""


def extract_domain(url: str) -> str:
    return urlparse(url).netloc


def save_outputs(cleaned_data: list, chosen_formats: list) -> list:
    """Dispatches data to the chosen output formats. Returns list of saved file paths."""
    format_map = {
        "csv": (save_to_csv, "scraped_data.csv"),
        "json": (save_to_json, "scraped_data.json"),
        "txt": (save_to_txt, "scraped_data.txt"),
        "xlsx": (save_to_excel, "scraped_data.xlsx"),
    }

    if "all" in chosen_formats:
        chosen_formats = list(format_map.keys())

    saved_files = []
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    for fmt in chosen_formats:
        fmt = fmt.strip().lower()
        if fmt in format_map:
            save_fn, filename = format_map[fmt]
            save_fn(cleaned_data)
            filepath = (output_dir / filename).resolve()
            saved_files.append(str(filepath))
        else:
            general_log.warning(f"Unknown format: '{fmt}'. Skipping.")

    return saved_files


async def process_single_url(context, url: str) -> list:
    """Processes a single URL and returns a list of cleaned data objects."""
    mode = detect_mode(url)
    general_log.info("=" * 60)
    general_log.info(f"Target URL:    {url}")
    general_log.info(f"Domain:        {extract_domain(url)}")
    general_log.info(f"Detected Mode: {mode.upper()}")
    general_log.info("=" * 60)

    if not url.startswith("http"):
        general_log.error(f"Invalid URL: {url}")
        return []

    # ── Step 1: Fetch Page ──
    try:
        html = await fetch_page(url, context)
    except BlockingError as e:
        general_log.critical(f"BLOCKED fetching {url}: {e}")
        return []
    except Exception as e:
        general_log.critical(f"FATAL NETWORK ERROR for {url}: {e}")
        return []

    if not html:
        general_log.error(f"No HTML content retrieved for {url}.")
        return []

    general_log.info(f"HTML retrieved successfully ({len(html)} bytes) for {url}.")

    # ── Step 2: Cache Raw HTML ──
    cache_html(html, url)

    # ── Step 3: Parse & Clean ──
    raw_data = parse_data(html, url, mode=mode)
    
    cleaned_data = []
    if mode == "profile":
        p_clean = clean_business_profile(raw_data)
        cleaned_data.append(p_clean)
        business_name = p_clean.get("business", {}).get("name")
        general_log.info(f"Extraction complete: Business Profile: {business_name}")
    else:
        # Multi-level crawl logic
        profile_links = raw_data.get("Profile_Links", [])
        general_log.info(f"Listing parsed for {url}. Found {len(profile_links)} direct business profiles.")
        
        for i, p_url in enumerate(profile_links, 1):
            general_log.info(f"--- Scraping Profile {i}/{len(profile_links)}: {p_url} ---")
            try:
                p_html = await fetch_page(p_url, context)
                if p_html:
                    p_raw = parse_data(p_html, p_url, mode="profile")
                    p_clean = clean_business_profile(p_raw)
                    cleaned_data.append(p_clean)
            except Exception as e:
                general_log.error(f"Failed to scrape child profile {p_url}: {e}")
                
        general_log.info(f"Extraction complete for {url}: {len(cleaned_data)} profiles extracted.")

    return cleaned_data


async def main_async(url_input: str, headless: bool, proxy: str = None, formats: str = None):
    print(BANNER)
    general_log.info(f"Browser:       {'Headless' if headless else 'Headful'}")

    urls = []
    if os.path.isfile(url_input):
        try:
            with open(url_input, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            general_log.info(f"Loaded {len(urls)} URLs from file: {url_input}")
        except Exception as e:
            general_log.error(f"Failed to read file {url_input}: {e}")
            sys.exit(1)
    else:
        urls = [u.strip() for u in url_input.split(",") if u.strip()]

    if not urls:
        general_log.error("No valid URLs found to process.")
        sys.exit(1)

    chosen = [f.strip() for f in formats.split(",")] if formats else ["json"]
    all_collected_data = []
    successful_urls = []
    failed_urls = []
    
    # Controlled concurrency logic
    BATCH_SIZE = 4 

    async with async_playwright() as p:
        browser, context = await browser_initializer(p, headless=headless, proxy=proxy)
        try:
            for i in range(0, len(urls), BATCH_SIZE):
                chunk = urls[i:i+BATCH_SIZE]
                general_log.info(f"\n>>> Processing Batch {i//BATCH_SIZE + 1} ({len(chunk)} target URLs concurrently)...")
                
                tasks = [process_single_url(context, u) for u in chunk]
                # Gather concurrent background tabs
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for output, target_url in zip(results, chunk):
                    if isinstance(output, Exception):
                        general_log.error(f"Unexpected error processing {target_url}: {output}")
                        failed_urls.append(target_url)
                    elif output:  # list with elements
                        all_collected_data.extend(output)
                        successful_urls.append(target_url)
                        print(f"Extracted data from: {target_url} (Found {len(output)} records)")
                    else:
                        failed_urls.append(target_url)
                        general_log.warning(f"No data extracted from: {target_url}")
                        
                print(f"Batch Done. Overall Progress: {min(i + BATCH_SIZE, len(urls))}/{len(urls)}")
                
                # Tiny throttle between batches to avoid IP block cascades
                if (i + BATCH_SIZE) < len(urls):
                    await asyncio.sleep(random.uniform(1.0, 3.0))
        finally:
            await browser.close()

    item_label = f"Total Business Profiles Extracted: {len(all_collected_data)}"

    # ── Save Output Logic ──
    if not formats:
        print("\n" + "=" * 50)
        print(f"  {item_label}")
        print("  Generating strict nested JSON format...")
        print("=" * 50)

    saved_files = []
    if all_collected_data:
        saved_files = save_outputs(all_collected_data, chosen)
    else:
        general_log.warning("No valid data collected to save.")

    output_dir = Path("output").resolve()

    print("\n" + "=" * 60)
    print("  ✅ SCRAPING COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print(f"  {item_label}")
    print(f"  Total URLs processed: {len(urls)}")
    print(f"  Successful: {len(successful_urls)}")
    print(f"  Failed: {len(failed_urls)}\n")

    if successful_urls:
        print("  Successful URLs:")
        for su in successful_urls:
            print(f"  - {su}")
        print()

    if failed_urls:
        print("  Failed URLs:")
        for fu in failed_urls:
            print(f"  - {fu}")
        print()

    if saved_files:
        print("  📁 Generated Files:")
        for fpath in saved_files:
            print(f"     → {fpath}")
    print()
    print(f"  📂 Output Folder: {output_dir}")
    print(f"  📋 Logs Folder:   {Path('.logs').resolve()}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Advanced Stealth Web Scraper — Playwright Async + Deep DOM Engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", nargs="?", default=None, help="Target URL, comma-separated URLs, or path to text file containing URLs")
    parser.add_argument("--headful", action="store_true", default=False, help="Run browser in visible mode (default is headless)")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy string, e.g. http://user:pass@host:port")
    parser.add_argument("--formats", type=str, default=None, help="Comma-separated output formats: csv,json,txt,xlsx,all")

    args = parser.parse_args()
    headless_mode = not args.headful

    url = args.url
    if not url:
        print(BANNER)
        print("  Welcome! Enter a URL, multiple URLs (comma-separated), or a file path.\n")
        try:
            url = input("  🔗 Enter Input: ").strip()
        except EOFError:
            pass
        if not url:
            print("  No URL provided. Exiting.")
            sys.exit(0)

    try:
        asyncio.run(main_async(url, headless=headless_mode, proxy=args.proxy, formats=args.formats))
    except KeyboardInterrupt:
        general_log.warning("Interrupted by user. Exiting safely.")
        sys.exit(0)


if __name__ == "__main__":
    main()
