import asyncio
import argparse
import os
import sys
import random
# import threading  # Only needed for alarm system
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

# # Windows fallback for sound
# try:
#     import winsound
# except ImportError:
#     winsound = None

from playwright.async_api import async_playwright
from scraper.logger import general_log
from scraper.network import fetch_page, BlockingError, VPNDisconnectError, browser_initializer
from scraper.parser import parse_data
from scraper.cleaner import clean_and_validate, clean_business_profile
from scraper.storage import cache_html, save_to_csv, save_to_txt, save_to_json, save_to_excel


# # ─── Sound Alert System (COMMENTED OUT) ─────────────────────────────────────
# # Global blocking detection with single-fire alert.
# # How it works:
# #   • _is_blocked = False  →  system is "clear"
# #   • First block detected →  play sound ONCE, set _is_blocked = True
# #   • Subsequent blocks   →  NO sound (already alerting)
# #   • Successful request   →  reset _is_blocked = False
# #   • Next new block       →  sound fires again (new disconnection event)
#
# # ── Master Toggle: set to True to re-enable alert sounds & banners ──
# ENABLE_ALERT = False
#
# ALERT_SOUND_PATH = Path(__file__).parent / "alert.mpeg"
#
# _is_blocked = False               # Global state: True = currently in a blocked state
# _alert_lock = threading.Lock()    # Thread-safe guard for alert state
#
# def reset_blocking_state():
#     """Resets the blocked flag (called on successful network requests)."""
#     global _is_blocked
#     with _alert_lock:
#         if _is_blocked:
#             _is_blocked = False
#             general_log.info("Resetting global blocking state (successful request).")
#
#
# def _play_alert_sound():
#     """
#     Plays the alert sound ONCE for a new disconnection event.
#     Uses pygame at 80% volume; falls back to native Windows beep.
#     Called only when _is_blocked transitions from False → True.
#     Respects the ENABLE_ALERT toggle.
#     """
#     if not ENABLE_ALERT:
#         general_log.debug("Alert sound skipped (ENABLE_ALERT = False).")
#         return
#
#     def _play_worker():
#         # --- PHASE 1: Try Pygame (High Quality) ---
#         try:
#             import pygame
#
#             if not ALERT_SOUND_PATH.exists():
#                 general_log.warning(f"Alert sound file not found: {ALERT_SOUND_PATH}")
#                 # Fallthrough to winsound below
#             else:
#                 if not pygame.mixer.get_init():
#                     pygame.mixer.init()
#
#                 pygame.mixer.music.load(str(ALERT_SOUND_PATH.resolve()))
#                 pygame.mixer.music.set_volume(0.80)
#                 pygame.mixer.music.play()
#
#                 while pygame.mixer.music.get_busy():
#                     pygame.time.Clock().tick(10)
#
#                 general_log.info("🔊 Alert sound played via pygame at 80% volume.")
#                 return  # Success!
#
#         except Exception as e:
#             general_log.warning(f"Pygame sound failed (falling back to winsound): {e}")
#
#         # --- PHASE 2: Fallback to Native Windows (Very Reliable) ---
#         if winsound:
#             try:
#                 winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
#                 general_log.info("🔔 Alert sound played via Windows MessageBeep (fallback).")
#             except Exception as be:
#                 general_log.error(f"Fallback sound also failed: {be}")
#         else:
#             print("\a")  # Final beep fallback
#             general_log.warning("No audio system available. Triggered system console beep (\\a).")
#
#     # Fire in background thread so it doesn't block scraping
#     threading.Thread(target=_play_worker, daemon=True).start()
#
#
# def reset_alert_for_new_session():
#     """Resets the alert state — call at the start of a session or a retry task."""
#     global _is_blocked
#     with _alert_lock:
#         _is_blocked = False
#     general_log.info("Alert and blocking state reset for new session.")


# # ─── Blocking / VPN Callback (COMMENTED OUT) ────────────────────────────────
#
# def on_blocking_detected(url: str, reason: str):
#     """
#     Callback fired by network layer on blocking or VPN disconnection.
#     
#     First detection  →  full console banner + alert sound + set _is_blocked = True
#     Subsequent hits  →  compact one-line log (no sound, no banner spam)
#     """
#     global _is_blocked
#
#     timestamp = datetime.now().strftime("%H:%M:%S")
#     general_log.critical(f"🚨 BLOCKING — {reason} — {url}")
#
#     with _alert_lock:
#         if not _is_blocked:
#             # ── First block in this disconnection event ──
#             _is_blocked = True
#             if ENABLE_ALERT:
#                 print()
#                 print("🚨" * 20)
#                 print(f"  🚨🚨🚨  BLOCKING ALERT  [{timestamp}]  🚨🚨🚨")
#                 print(f"  URL:    {url}")
#                 print(f"  Reason: {reason}")
#                 print("🚨" * 20)
#                 print()
#                 _play_alert_sound()
#             else:
#                 general_log.info(f"Block detected (alerts disabled): {url} — {reason}")
#             general_log.info(f"Global blocked state: ON (first block at {url})")
#         else:
#             # ── Already blocked — compact output, NO sound ──
#             if ENABLE_ALERT:
#                 print(f"  🚨 [{timestamp}] Still blocked — {url} ({reason})")
#             general_log.debug(f"Subsequent block (suppressed sound): {url}")

# Stub replacements so call sites don't break
def on_blocking_detected(url: str, reason: str):
    """No-op stub — alarm system commented out."""
    general_log.critical(f"🚨 BLOCKING — {reason} — {url}")

def reset_blocking_state():
    """No-op stub — alarm system commented out."""
    pass

def reset_alert_for_new_session():
    """No-op stub — alarm system commented out."""
    pass


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
║              ADVANCED STEALTH WEB SCRAPER v2.0               ║
║     Playwright-Powered · Anti-Detection · Smart Retry        ║
║        10x Concurrency · VPN Alert · Sound Notifier          ║
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


# ─── Core URL Processor (unchanged extraction logic) ─────────────────────────

async def process_single_url(context, url: str, index: int, total: int) -> list:
    """Processes a single URL and returns a list of cleaned data objects."""
    mode = detect_mode(url)
    general_log.info("=" * 60)
    general_log.info(f"[{index}/{total}] Target URL: {url}")
    general_log.info(f"Domain: {extract_domain(url)} | Mode: {mode.upper()}")
    general_log.info("=" * 60)

    if not url.startswith("http"):
        general_log.error(f"Invalid URL: {url}")
        return []

    # ── Step 1: Fetch Page ──
    try:
        html = await fetch_page(url, context, on_blocking_detected=on_blocking_detected)
        # SUCCESS: Reset blocking state if fetch succeeded
        if html:
            reset_blocking_state()
    except BlockingError as e:
        general_log.critical(f"BLOCKED fetching {url}: {e}")
        return []
    except VPNDisconnectError as e:
        general_log.critical(f"VPN/NETWORK DOWN for {url}: {e}")
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

    # ── Step 3: Parse & Clean (UNCHANGED EXTRACTION LOGIC) ──
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
                p_html = await fetch_page(p_url, context, on_blocking_detected=on_blocking_detected)
                if p_html:
                    reset_blocking_state()
                    p_raw = parse_data(p_html, p_url, mode="profile")
                    p_clean = clean_business_profile(p_raw)
                    cleaned_data.append(p_clean)
            except Exception as e:
                general_log.error(f"Failed to scrape child profile {p_url}: {e}")
                
        general_log.info(f"Extraction complete for {url}: {len(cleaned_data)} profiles extracted.")

    return cleaned_data


# ─── Batch Processing Engine ─────────────────────────────────────────────────

async def run_batch(
    context,
    urls: list,
    all_collected_data: list,
    successful_urls: list,
    failed_urls: list,
    batch_size: int = 10,
    global_offset: int = 0,
):
    """Process URLs in controlled async batches using a semaphore."""
    total = len(urls) + global_offset
    sem = asyncio.Semaphore(batch_size)

    processed_count = 0
    progress_lock = asyncio.Lock()

    async def sem_process(url, idx):
        nonlocal processed_count
        try:
            async with sem:
                return await process_single_url(context, url, idx, total)
        finally:
            async with progress_lock:
                processed_count += 1
                # Display immediate completion status after each URL regardless of success/failure
                print(f"  🏁 Completed: {processed_count + global_offset} / {total}")

    for i in range(0, len(urls), batch_size):
        chunk = urls[i:i + batch_size]
        batch_num = i // batch_size + 1
        chunk_start = i + global_offset + 1
        chunk_end = min(i + batch_size, len(urls)) + global_offset

        print(f"\n{'─' * 60}")
        print(f"  📦 Batch {batch_num}  |  Processing {chunk_start}-{chunk_end} / {total}")
        print(f"{'─' * 60}")

        tasks = [
            sem_process(url, i + j + global_offset + 1)
            for j, url in enumerate(chunk)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for output, target_url in zip(results, chunk):
            if isinstance(output, Exception):
                general_log.error(f"Unexpected error processing {target_url}: {output}")
                failed_urls.append(target_url)
            elif output:
                all_collected_data.extend(output)
                successful_urls.append(target_url)
                print(f"  ✅ Done: {target_url} ({len(output)} records)")
            else:
                failed_urls.append(target_url)
                general_log.warning(f"No data extracted from: {target_url}")
                print(f"  ❌ Failed: {target_url}")

        done_count = min(i + batch_size, len(urls)) + global_offset
        print(f"\n  📊 Progress: {done_count} / {total}  |  "
              f"✅ {len(successful_urls)}  ❌ {len(failed_urls)}")

        # Tiny throttle between batches to avoid IP block cascades
        if (i + batch_size) < len(urls):
            delay = random.uniform(1.0, 3.0)
            print(f"  ⏳ Throttling {delay:.1f}s before next batch...")
            await asyncio.sleep(delay)


# ─── Final Summary ───────────────────────────────────────────────────────────

def print_summary(
    total_urls: int,
    successful_urls: list,
    failed_urls: list,
    all_collected_data: list,
    saved_files: list,
):
    """Prints a comprehensive final summary."""
    item_label = f"Total Business Profiles Extracted: {len(all_collected_data)}"
    output_dir = Path("output").resolve()

    print("\n" + "═" * 60)
    print("  ✅ SCRAPING COMPLETED!")
    print("═" * 60)
    print(f"  {item_label}")
    print(f"  Total URLs Processed: {total_urls}")
    print(f"  ✅ Successful: {len(successful_urls)}")
    print(f"  ❌ Failed:     {len(failed_urls)}")
    print()

    if successful_urls:
        print("  ── Successful URLs ──")
        for su in successful_urls:
            print(f"    ✅ {su}")
        print()

    if failed_urls:
        print("  ── Failed URLs ──")
        for fu in failed_urls:
            print(f"    ❌ {fu}")
        print()

    if saved_files:
        print("  📁 Generated Files:")
        for fpath in saved_files:
            print(f"     → {fpath}")
    print()
    print(f"  📂 Output Folder: {output_dir}")
    print(f"  📋 Logs Folder:   {Path('.logs').resolve()}")
    print("═" * 60 + "\n")


# ─── Retry Failed URLs ───────────────────────────────────────────────────────

async def retry_failed_urls(
    context,
    failed_urls: list,
    all_collected_data: list,
    successful_urls: list,
    chosen_formats: list,
):
    """Retry only the failed URLs using the same scraping logic."""
    print("\n" + "─" * 60)
    print(f"  🔄 RETRYING {len(failed_urls)} FAILED URLs...")
    print("─" * 60)

    retry_failed = []
    retry_success = []

    # Reset alert so it can fire again during retry
    reset_alert_for_new_session()

    await run_batch(
        context=context,
        urls=failed_urls,
        all_collected_data=all_collected_data,
        successful_urls=retry_success,
        failed_urls=retry_failed,
        batch_size=10,
        global_offset=0,
    )

    # Update the main lists
    successful_urls.extend(retry_success)

    # Save updated data
    saved_files = []
    if all_collected_data:
        saved_files = save_outputs(all_collected_data, chosen_formats)

    print("\n" + "═" * 60)
    print("  🔄 RETRY RESULTS")
    print("═" * 60)
    print(f"  Retried: {len(failed_urls)} URLs")
    print(f"  ✅ Now Successful: {len(retry_success)}")
    print(f"  ❌ Still Failed:   {len(retry_failed)}")
    print()

    if retry_success:
        print("  ── Recovered URLs ──")
        for su in retry_success:
            print(f"    ✅ {su}")
        print()

    if retry_failed:
        print("  ── Permanently Failed URLs ──")
        for fu in retry_failed:
            print(f"    ❌ {fu}")
        print()

    if saved_files:
        print("  📁 Updated Files:")
        for fpath in saved_files:
            print(f"     → {fpath}")
    print("═" * 60 + "\n")

    return retry_failed


# ─── Main Async Entry Point ──────────────────────────────────────────────────

async def main_async(url_input: str, headless: bool, proxy: str = None, formats: str = None):
    # Reset alert flag at the start of a new scraping session
    reset_alert_for_new_session()
    
    print(BANNER)
    general_log.info(f"Browser:       {'Headless' if headless else 'Headful'}")
    general_log.info(f"Concurrency:   10 parallel tabs (controlled semaphore)")

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
    
    BATCH_SIZE = 10  # Increased from 4 → 10

    async with async_playwright() as p:
        browser, context = await browser_initializer(p, headless=headless, proxy=proxy)
        try:
            # ── Main Scraping Run ──
            await run_batch(
                context=context,
                urls=urls,
                all_collected_data=all_collected_data,
                successful_urls=successful_urls,
                failed_urls=failed_urls,
                batch_size=BATCH_SIZE,
            )

            # ── Save Output ──
            saved_files = []
            if all_collected_data:
                saved_files = save_outputs(all_collected_data, chosen)
            else:
                general_log.warning("No valid data collected to save.")

            # ── Final Summary ──
            print_summary(
                total_urls=len(urls),
                successful_urls=successful_urls,
                failed_urls=failed_urls,
                all_collected_data=all_collected_data,
                saved_files=saved_files,
            )

            # ── Retry Prompt ──
            if failed_urls:
                try:
                    answer = input(f"\n  🔄 {len(failed_urls)} URLs failed. Do you want to retry failed URLs? (yes/no): ").strip().lower()
                    if answer in ("yes", "y"):
                        still_failed = await retry_failed_urls(
                            context=context,
                            failed_urls=failed_urls.copy(),
                            all_collected_data=all_collected_data,
                            successful_urls=successful_urls,
                            chosen_formats=chosen,
                        )
                        # Final updated summary
                        if still_failed:
                            print(f"  ℹ️  {len(still_failed)} URLs remain failed after retry.\n")
                        else:
                            print("  🎉 All previously failed URLs recovered successfully!\n")
                    else:
                        print("  ⏩ Skipping retry.\n")
                except EOFError:
                    print("  ⏩ Non-interactive mode, skipping retry.\n")
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser(
        description="Advanced Stealth Web Scraper v2.0 — 10x Concurrency + Smart Retry + VPN Alerts.",
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
