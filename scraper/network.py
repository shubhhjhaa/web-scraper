import time
import random
import math
from typing import Optional
from fake_useragent import UserAgent
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from .logger import network_log, blocking_log, general_log
from .stealth import apply_stealth

ua = UserAgent(fallback='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


class ScraperError(Exception):
    """General error for failing to fetch."""
    pass


class BlockingError(Exception):
    """Error raised when CAPTCHA, anti-bot, or 403/429 is detected."""
    pass


# ─── Viewport & Device Profiles ───────────────────────────────────────────────

DEVICE_PROFILES = [
    {"width": 1920, "height": 1080, "device_scale_factor": 1},
    {"width": 1366, "height": 768,  "device_scale_factor": 1},
    {"width": 1536, "height": 864,  "device_scale_factor": 1.25},
    {"width": 1440, "height": 900,  "device_scale_factor": 1},
    {"width": 1280, "height": 720,  "device_scale_factor": 1},
    {"width": 1600, "height": 900,  "device_scale_factor": 1},
]

LOCALES = ["en-US", "en-GB", "en-IN", "en-AU"]
TIMEZONES = ["Asia/Kolkata", "America/New_York", "Europe/London", "Asia/Singapore"]


# ─── Proxy Manager ────────────────────────────────────────────────────────────

def proxy_manager(proxy_string: Optional[str] = None) -> Optional[dict]:
    """
    Parses a proxy string into Playwright-compatible proxy config.
    Accepts format: http://username:password@host:port  OR  http://host:port
    Returns None if no proxy provided.
    """
    if not proxy_string:
        return None

    general_log.info(f"Configuring proxy: {proxy_string[:30]}...")
    proxy_config = {"server": proxy_string}

    # Extract credentials if present (format: http://user:pass@host:port)
    if "@" in proxy_string:
        try:
            proto_rest = proxy_string.split("://", 1)
            proto = proto_rest[0]
            creds_host = proto_rest[1]
            creds, host_port = creds_host.rsplit("@", 1)
            username, password = creds.split(":", 1)
            proxy_config = {
                "server": f"{proto}://{host_port}",
                "username": username,
                "password": password,
            }
        except (ValueError, IndexError):
            general_log.warning("Could not parse proxy credentials. Using raw proxy string.")
            proxy_config = {"server": proxy_string}

    return proxy_config


# ─── Browser Initializer ──────────────────────────────────────────────────────

def browser_initializer(
    playwright_instance,
    headless: bool = False,
    proxy: Optional[str] = None
) -> tuple[Browser, BrowserContext]:
    """
    Launches Chromium with stealth patches, randomized fingerprint.
    Returns (browser, context).
    """
    general_log.info(f"Initializing browser (headless={headless})...")

    profile = random.choice(DEVICE_PROFILES)
    locale = random.choice(LOCALES)
    timezone = random.choice(TIMEZONES)
    user_agent = ua.random

    launch_args = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--start-maximized",
        ],
    }

    proxy_config = proxy_manager(proxy)
    if proxy_config:
        launch_args["proxy"] = proxy_config

    browser = playwright_instance.chromium.launch(**launch_args)

    context = browser.new_context(
        user_agent=user_agent,
        viewport={"width": profile["width"], "height": profile["height"]},
        device_scale_factor=profile["device_scale_factor"],
        locale=locale,
        timezone_id=timezone,
        java_script_enabled=True,
        permissions=["geolocation"],
        color_scheme=random.choice(["light", "dark", "no-preference"]),
    )

    general_log.info(
        f"Browser profile: {profile['width']}x{profile['height']} | "
        f"locale={locale} | tz={timezone} | agent={user_agent[:50]}..."
    )

    return browser, context


# ─── Human Behavior Simulator ─────────────────────────────────────────────────

def human_behavior_simulator(page: Page) -> None:
    """
    Simulates realistic human browsing behavior on the page.
    Includes mouse movement, scrolling, and random pauses.
    """
    general_log.info("Simulating human behavior...")
    viewport = page.viewport_size or {"width": 1920, "height": 1080}
    vw, vh = viewport["width"], viewport["height"]

    # 1. Random mouse movements with Bezier-like intermediate points
    for _ in range(random.randint(2, 5)):
        target_x = random.randint(100, vw - 100)
        target_y = random.randint(100, vh - 100)
        # Move in small steps to look natural
        steps = random.randint(5, 15)
        try:
            page.mouse.move(target_x, target_y, steps=steps)
        except Exception:
            pass
        time.sleep(random.uniform(0.1, 0.4))

    # 2. Gradual scroll simulation (not instant jumps)
    scroll_count = random.randint(3, 7)
    for i in range(scroll_count):
        scroll_amount = random.randint(200, 600)
        page.evaluate(f"""
            window.scrollBy({{
                top: {scroll_amount},
                left: 0,
                behavior: 'smooth'
            }});
        """)
        time.sleep(random.uniform(0.8, 2.5))

        # Occasionally scroll up slightly (humans do this)
        if random.random() < 0.3:
            up_amount = random.randint(50, 150)
            page.evaluate(f"""
                window.scrollBy({{
                    top: -{up_amount},
                    left: 0,
                    behavior: 'smooth'
                }});
            """)
            time.sleep(random.uniform(0.3, 0.8))

    # 3. Random mouse hover over elements
    try:
        links = page.query_selector_all("a")
        if links and len(links) > 3:
            for link in random.sample(links, min(3, len(links))):
                box = link.bounding_box()
                if box:
                    page.mouse.move(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                        steps=random.randint(3, 8),
                    )
                    time.sleep(random.uniform(0.2, 0.6))
    except Exception:
        pass  # Non-critical

    # 4. Final deliberate pause
    time.sleep(random.uniform(1.0, 3.0))
    general_log.info("Human behavior simulation completed.")


# ─── Anti-Bot Detection ───────────────────────────────────────────────────────

CAPTCHA_SIGNALS = [
    "captcha", "recaptcha", "g-recaptcha", "h-captcha",
    "verify you are a human", "press & hold", "press and hold",
    "attention required", "checking your browser",
    "just a moment", "please wait", "access denied",
    "datadome", "perimeterx", "kasada",
    "bot protection", "are you a robot",
]

BLOCKING_SIGNALS = [
    "403 forbidden", "429 too many requests",
    "you have been blocked", "access to this page has been denied",
    "sorry, you have been blocked",
]


def anti_bot_detection(page: Page) -> None:
    """
    Scans the current page for CAPTCHA, blocking signals, or honeypots.
    Raises BlockingError if detected. Does NOT continue blindly.
    """
    try:
        content = page.content().lower()
        title = page.title().lower()
    except Exception:
        return  # Page might have navigated away

    all_text = content + " " + title

    # Check for captcha / challenge pages
    for signal in CAPTCHA_SIGNALS:
        if signal in all_text:
            blocking_log.warning(f"Anti-bot signal detected: '{signal}'")
            raise BlockingError(f"Anti-bot challenge detected: '{signal}'. Stopping safely.")

    # Check for explicit blocking
    for signal in BLOCKING_SIGNALS:
        if signal in all_text:
            blocking_log.warning(f"Blocking signal detected: '{signal}'")
            raise BlockingError(f"Page blocked: '{signal}'. Stopping safely.")

    # Check for honeypot hidden fields
    try:
        honeypots = page.query_selector_all('input[type="hidden"][name*="honey"], input[style*="display:none"]')
        if honeypots and len(honeypots) > 3:
            blocking_log.warning("Potential honeypot inputs detected.")
    except Exception:
        pass

    general_log.info("Anti-bot check passed. Page appears clean.")


# ─── Page Complexity Detection ─────────────────────────────────────────────────

def detect_page_complexity(page: Page) -> dict:
    """
    Analyzes the loaded page for pagination, infinite scroll, lazy loading signals.
    Returns a dict of detected features.
    """
    general_log.info("Analyzing page complexity...")
    result = {
        "has_pagination": False,
        "has_infinite_scroll": False,
        "has_lazy_loading": False,
        "total_items_estimate": 0,
    }

    try:
        # Check for pagination links
        pagination_selectors = [
            "nav[aria-label*='pagination']", ".pagination", "[class*='paginator']",
            "a[href*='page=']", "a[href*='p=']", "[class*='paginat']",
            "ul.pagination", ".page-numbers",
        ]
        for sel in pagination_selectors:
            if page.query_selector(sel):
                result["has_pagination"] = True
                break

        # Check for infinite scroll signals
        scroll_indicators = page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script');
                let hasInfinite = false;
                scripts.forEach(s => {
                    if (s.textContent && (
                        s.textContent.includes('IntersectionObserver') ||
                        s.textContent.includes('infinite') ||
                        s.textContent.includes('loadMore') ||
                        s.textContent.includes('load_more')
                    )) hasInfinite = true;
                });
                return hasInfinite;
            }
        """)
        result["has_infinite_scroll"] = scroll_indicators

        # Check for lazy loading images
        lazy_images = page.query_selector_all("img[loading='lazy'], img[data-src], img[data-lazy]")
        result["has_lazy_loading"] = len(lazy_images) > 0

        # Estimate item count
        card_selectors = ["[class*='product']", "[class*='card']", "[class*='item']", "[data-id]"]
        for sel in card_selectors:
            items = page.query_selector_all(sel)
            if items and len(items) > result["total_items_estimate"]:
                result["total_items_estimate"] = len(items)

    except Exception as e:
        general_log.warning(f"Complexity detection partial failure: {e}")

    general_log.info(f"Page complexity: {result}")
    return result


# ─── Scroll To Load All Content ───────────────────────────────────────────────

def scroll_to_load_all(page: Page, max_scrolls: int = 15) -> None:
    """
    Scrolls the page gradually to trigger lazy loading and infinite scroll.
    Stops when no new content appears or max scroll count is reached.
    """
    general_log.info("Scrolling to load all dynamic content...")
    previous_height = 0

    for i in range(max_scrolls):
        current_height = page.evaluate("document.body.scrollHeight")
        if current_height == previous_height and i > 2:
            general_log.info(f"No new content after scroll {i}. Stopping scroll.")
            break

        previous_height = current_height

        # Smooth scroll down
        scroll_target = random.randint(
            int(current_height * 0.3),
            int(current_height * 0.8)
        )
        page.evaluate(f"window.scrollTo({{ top: {scroll_target}, behavior: 'smooth' }})")
        time.sleep(random.uniform(1.0, 2.0))

        # Full bottom scroll
        page.evaluate("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })")
        time.sleep(random.uniform(1.5, 3.0))

    # Scroll back to top for clean parsing
    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    time.sleep(0.5)
    general_log.info("Dynamic content scroll completed.")


def reveal_hidden_content(page: Page) -> None:
    """
    Identifies and clicks buttons that reveal hidden information 
    like phone numbers, emails, or expandable 'About' sections.
    Common on business directories like Hipages, Trustpilot, etc.
    """
    general_log.info("Checking for 'Reveal' buttons (Phone, View More)...")
    reveal_selectors = [
        "button:has-text('Reveal')", 
        "button:has-text('Show Number')",
        "button:has-text('View More')",
        "a:has-text('Show Number')",
        "[class*='reveal']",
        "[class*='show-number']",
        "button:has-text('Contact Details')",
    ]
    
    for sel in reveal_selectors:
        try:
            # Find all matching visible buttons
            buttons = page.query_selector_all(sel)
            for btn in buttons:
                if btn.is_visible():
                    general_log.info(f"Clicking reveal button: {sel}")
                    btn.click()
                    time.sleep(random.uniform(0.5, 1.5))
        except Exception:
            continue

    general_log.info("Reveal check completed.")


# ─── Core Fetch Page ──────────────────────────────────────────────────────────

# Retry decorator
fetch_retry = retry(
    wait=wait_exponential(multiplier=2, min=3, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(ScraperError),
    reraise=True,
)


@fetch_retry
def fetch_page(url: str, context: BrowserContext) -> str:
    """
    The main orchestrator. Reuses a stealthy Playwright browser context,
    opens a new tab for the URL, simulates human behavior, checks for blocking,
    scrolls to load dynamic content, and returns the fully rendered HTML.
    """
    general_log.info(f"{'='*50}")
    general_log.info(f"Fetching: {url}")

    page = None
    try:
        page = context.new_page()

        # Apply stealth patches
        apply_stealth(page)

        # Navigate
        general_log.info("Navigating to target URL...")
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        initial_status = response.status if response else 0

        # Log status but don't abort yet — JS challenges may resolve
        if initial_status in [403, 429]:
            blocking_log.warning(f"HTTP {initial_status} received — waiting for JS challenge to resolve...")
            time.sleep(random.uniform(5.0, 8.0))

        # Wait for network to settle
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            general_log.warning("Network did not reach idle state. Continuing with what we have...")

        # Small pause to let JS render finish
        time.sleep(random.uniform(2.0, 4.0))

        # Re-check if page actually has content now (post-challenge)
        page_text = page.evaluate("document.body ? document.body.innerText : ''").lower()

        # If page is still showing a challenge or is empty, try waiting once more
        challenge_words = ["checking your browser", "just a moment", "please wait", "enable javascript", "cloudflare"]
        if any(w in page_text for w in challenge_words):
            general_log.info("JS challenge page detected, waiting longer for resolution...")
            time.sleep(random.uniform(8.0, 15.0))
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

        # Update page_text post-wait
        page_text = page.evaluate("document.body ? document.body.innerText : ''").lower()

        # NOW check for real blocking (after JS has had time to resolve)
        anti_bot_detection(page)

        # Simulate human behavior
        human_behavior_simulator(page)

        # Detect complexity
        complexity = detect_page_complexity(page)
        
        # Click buttons to reveal phone/more
        reveal_hidden_content(page)
        
        # Scroll to load lazy / infinite content
        if complexity["has_lazy_loading"] or complexity["has_infinite_scroll"]:
            scroll_to_load_all(page, max_scrolls=12)
        else:
            # Still scroll a bit even for static-looking pages
            scroll_to_load_all(page, max_scrolls=5)

        # Re-check for reveals after scrolling (some appear late)
        reveal_hidden_content(page)
        
        # Final anti-bot check after scrolling
        anti_bot_detection(page)

        # Extract rendered HTML
        html = page.content()
        general_log.info(f"Page rendered. HTML size: {len(html)} bytes")

        return html

    except BlockingError:
        raise  # Propagate blocking errors cleanly
    except Exception as e:
        network_log.error(f"Fetch failed for {url}: {e}")
        raise ScraperError(f"Fetch failed: {e}")
    finally:
        if page:
            page.close()
