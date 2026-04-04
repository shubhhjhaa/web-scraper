import asyncio
import random
import math
from typing import Optional
from fake_useragent import UserAgent
from playwright.async_api import async_playwright, Page, BrowserContext, Browser
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
    if not proxy_string: return None
    proxy_config = {"server": proxy_string}
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
            proxy_config = {"server": proxy_string}
    return proxy_config

# ─── Browser Initializer ──────────────────────────────────────────────────────

async def browser_initializer(
    playwright_instance,
    headless: bool = False,
    proxy: Optional[str] = None
) -> tuple[Browser, BrowserContext]:
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

    browser = await playwright_instance.chromium.launch(**launch_args)

    context = await browser.new_context(
        user_agent=user_agent,
        viewport={"width": profile["width"], "height": profile["height"]},
        device_scale_factor=profile["device_scale_factor"],
        locale=locale,
        timezone_id=timezone,
        java_script_enabled=True,
        permissions=["geolocation"],
        color_scheme=random.choice(["light", "dark", "no-preference"]),
    )
    return browser, context

# ─── Human Behavior Simulator ─────────────────────────────────────────────────

async def human_behavior_simulator(page: Page) -> None:
    general_log.info("Simulating human behavior...")
    viewport = page.viewport_size or {"width": 1920, "height": 1080}
    vw, vh = viewport["width"], viewport["height"]

    for _ in range(random.randint(2, 4)):
        target_x = random.randint(100, vw - 100)
        target_y = random.randint(100, vh - 100)
        steps = random.randint(5, 10)
        try:
            await page.mouse.move(target_x, target_y, steps=steps)
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.1, 0.3))

    scroll_count = random.randint(2, 4)
    for i in range(scroll_count):
        scroll_amount = random.randint(200, 600)
        await page.evaluate(f"window.scrollBy({{ top: {scroll_amount}, behavior: 'smooth' }});")
        await asyncio.sleep(random.uniform(0.5, 1.5))

# ─── Anti-Bot Detection ───────────────────────────────────────────────────────

CAPTCHA_SIGNALS = [
    "captcha", "recaptcha", "g-recaptcha", "h-captcha",
    "verify you are a human", "press & hold", "access denied",
    "bot protection", "are you a robot",
]

BLOCKING_SIGNALS = ["403 forbidden", "429 too many requests", "you have been blocked"]

async def anti_bot_detection(page: Page) -> None:
    try:
        content = (await page.content()).lower()
        title = (await page.title()).lower()
        all_text = content + " " + title
        
        for signal in CAPTCHA_SIGNALS:
            if signal in all_text:
                raise BlockingError(f"Anti-bot challenge detected: '{signal}'")

        for signal in BLOCKING_SIGNALS:
            if signal in all_text:
                raise BlockingError(f"Page blocked: '{signal}'")
    except BlockingError:
        raise
    except Exception:
        pass

# ─── Page Complexity Detection ─────────────────────────────────────────────────

async def detect_page_complexity(page: Page) -> dict:
    result = {"has_lazy_loading": False, "has_infinite_scroll": False}
    try:
        scroll_indicators = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script');
                let hasInfinite = false;
                scripts.forEach(s => {
                    if (s.textContent && (s.textContent.includes('IntersectionObserver') || s.textContent.includes('infinite') || s.textContent.includes('loadMore'))) hasInfinite = true;
                });
                return hasInfinite;
            }
        """)
        result["has_infinite_scroll"] = scroll_indicators
        
        lazy_images = await page.query_selector_all("img[loading='lazy'], img[data-src]")
        result["has_lazy_loading"] = len(lazy_images) > 0
    except Exception:
        pass
    return result

# ─── Scroll To Load All Content ───────────────────────────────────────────────

async def scroll_to_load_all(page: Page, max_scrolls: int = 5) -> None:
    previous_height = 0
    for i in range(max_scrolls):
        current_height = await page.evaluate("document.body.scrollHeight")
        if current_height == previous_height and i > 2:
            break
        previous_height = current_height

        scroll_target = random.randint(int(current_height * 0.3), int(current_height * 0.8))
        await page.evaluate(f"window.scrollTo({{ top: {scroll_target}, behavior: 'smooth' }})")
        await asyncio.sleep(random.uniform(0.5, 1.0))
        await page.evaluate("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })")
        await asyncio.sleep(random.uniform(1.0, 2.0))

    await page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    await asyncio.sleep(0.5)

async def reveal_hidden_content(page: Page) -> None:
    reveal_selectors = [
        "button:has-text('Reveal')", "button:has-text('Show Number')",
        "button:has-text('View More')", "a:has-text('Show Number')",
        "[class*='reveal']", "button:has-text('Contact Details')"
    ]
    for sel in reveal_selectors:
        try:
            buttons = await page.query_selector_all(sel)
            for btn in buttons:
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(random.uniform(0.5, 1.0))
        except Exception:
            continue

# ─── Core Fetch Page ──────────────────────────────────────────────────────────

fetch_retry = retry(
    wait=wait_exponential(multiplier=2, min=3, max=10),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(ScraperError),
    reraise=True,
)

@fetch_retry
async def fetch_page(url: str, context: BrowserContext) -> str:
    general_log.info(f"Fetching: {url}")
    page = None
    try:
        page = await context.new_page()
        await apply_stealth(page)

        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        initial_status = response.status if response else 0

        if initial_status in [403, 429]:
            await asyncio.sleep(random.uniform(3.0, 5.0))

        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        await anti_bot_detection(page)
        await human_behavior_simulator(page)
        
        complexity = await detect_page_complexity(page)
        await reveal_hidden_content(page)
        
        if complexity["has_lazy_loading"] or complexity["has_infinite_scroll"]:
            await scroll_to_load_all(page, max_scrolls=8)
        else:
            await scroll_to_load_all(page, max_scrolls=3)

        await reveal_hidden_content(page)
        await anti_bot_detection(page)

        html = await page.content()
        return html

    except BlockingError:
        raise
    except Exception as e:
        raise ScraperError(f"Fetch failed: {e}")
    finally:
        if page:
            await page.close()
