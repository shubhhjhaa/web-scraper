import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from scraper.logger import general_log
from scraper.network import fetch_page, BlockingError
from scraper.parser import parse_data
from scraper.cleaner import clean_and_validate, clean_business_profile
from scraper.storage import cache_html, save_to_csv, save_to_txt, save_to_json, save_to_excel


def detect_mode(url: str) -> str:
    """Auto-detects if URL is a listing page or a single business profile."""
    path = urlparse(url).path.lower()
    # Hipages logic
    if "/find/" in path:
        return "listing"
    if "/connect/" in path or "/tradie/" in path:
        return "profile"
    # Generic logic: if it's very deep or has common profile markers
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


def save_outputs(cleaned_data: dict, chosen_formats: list) -> list:
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


def main(url: str, headless: bool, proxy: str = None, formats: str = None):
    print(BANNER)
    mode = detect_mode(url)
    general_log.info("=" * 60)
    general_log.info(f"Target URL:    {url}")
    general_log.info(f"Domain:        {extract_domain(url)}")
    general_log.info(f"Detected Mode: {mode.upper()}")
    general_log.info(f"Browser:       {'Headless' if headless else 'Headful'}")
    general_log.info("=" * 60)

    if not url.startswith("http"):
        general_log.error("Invalid URL. Must start with http:// or https://")
        sys.exit(1)

    # ── Step 1: Fetch Page ──
    html = ""
    try:
        html = fetch_page(url, headless=headless, proxy=proxy)
    except BlockingError as e:
        general_log.critical(f"BLOCKED: {e}")
        general_log.critical("Scraper stopped safely to protect your IP. No data was saved.")
        sys.exit(1)
    except Exception as e:
        general_log.critical(f"FATAL NETWORK ERROR: {e}")
        sys.exit(1)

    if not html:
        general_log.error("No HTML content retrieved. Exiting.")
        sys.exit(1)

    general_log.info(f"HTML retrieved successfully ({len(html)} bytes).")

    # ── Step 2: Cache Raw HTML ──
    cache_html(html, url)

    # ── Step 3: Parse & Clean & Multi-Level Crawl ──
    raw_data = parse_data(html, url, mode=mode)
    
    if mode == "profile":
        cleaned_data = clean_business_profile(raw_data)
        item_label = f"Business Profile: {cleaned_data['business']['name']}"
        chosen = [f.strip() for f in formats.split(",")] if formats else ["json"]
    else:
        # Multi-level crawl logic
        profile_links = raw_data.get("Profile_Links", [])
        general_log.info(f"Listing parsed. Found {len(profile_links)} direct business profiles.")
        
        cleaned_data = []
        for i, p_url in enumerate(profile_links, 1):
            general_log.info(f"--- Scraping Profile {i}/{len(profile_links)} ---")
            try:
                # Small delay to remain stealthy
                p_html = fetch_page(p_url, headless=headless, proxy=proxy)
                if p_html:
                    p_raw = parse_data(p_html, p_url, mode="profile")
                    p_clean = clean_business_profile(p_raw)
                    if p_clean["business"]["name"]:  # Only append if valid
                        cleaned_data.append(p_clean)
            except Exception as e:
                general_log.error(f"Failed to scrape child profile {p_url}: {e}")
                
        item_label = f"Business Profiles Fully Extracted: {len(cleaned_data)}"
        chosen = [f.strip() for f in formats.split(",")] if formats else ["json"]

    general_log.info(f"Extraction complete: {item_label}")

    # ── Step 4: Save ──
    if not formats and mode != "profile":
        print("\n" + "=" * 50)
        print(f"  {item_label}")
        print("  Generating strict nested JSON format...")
        print("=" * 50)

    saved_files = save_outputs(cleaned_data, chosen)

    # ── Step 7: Show download paths and auto-open ──
    output_dir = Path("output").resolve()

    print("\n" + "=" * 60)
    print("  ✅ SCRAPING COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print(f"  {item_label}")
    print()
    print("  📁 Generated Files:")
    for fpath in saved_files:
        print(f"     → {fpath}")
    print()
    print(f"  📂 Output Folder: {output_dir}")
    print(f"  📋 Logs Folder:   {Path('.logs').resolve()}")
    print("=" * 60 + "\n")

    # Auto-open the output folder in file explorer
    try:
        if sys.platform == "win32":
            os.startfile(str(output_dir))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(output_dir)])
        else:
            subprocess.Popen(["xdg-open", str(output_dir)])
        general_log.info("Output folder opened automatically.")
    except Exception:
        general_log.info("Could not auto-open output folder. Please navigate manually.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Advanced Stealth Web Scraper — Playwright-powered with anti-detection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py "https://example.com"
  python main.py "https://flipkart.com/..." --formats csv,json
  python main.py "https://example.com" --headless --proxy "http://user:pass@ip:port" --formats all
        """
    )
    parser.add_argument("url", nargs="?", default=None, help="Target URL to scrape (if omitted, prompts interactively)")
    parser.add_argument(
        "--headless", action="store_true", default=False,
        help="Run browser in headless mode (default: headful/visible)"
    )
    parser.add_argument(
        "--proxy", type=str, default=None,
        help="Proxy string, e.g. http://user:pass@host:port"
    )
    parser.add_argument(
        "--formats", type=str, default=None,
        help="Comma-separated output formats: csv,json,txt,xlsx,all (if omitted, prompts interactively)"
    )

    args = parser.parse_args()

    # Interactive mode: prompt for URL if not provided
    url = args.url
    if not url:
        print(BANNER)
        print("  Welcome! Enter a URL to start scraping.\n")
        url = input("  🔗 Enter URL: ").strip()
        if not url:
            print("  No URL provided. Exiting.")
            sys.exit(0)

    try:
        main(url, headless=args.headless, proxy=args.proxy, formats=args.formats)
    except KeyboardInterrupt:
        general_log.warning("Interrupted by user. Exiting safely.")
        sys.exit(0)

