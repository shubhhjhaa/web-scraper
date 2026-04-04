import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .logger import parsing_log, general_log


# ─── Deep Extraction Patterns ───────────────────────────────────────────────

ABN_PATTERN = re.compile(r'\b(\d{2}\s*\d{3}\s*\d{3}\s*\d{3})\b')
LICENSE_PATTERN = re.compile(r'(?:Lic|License|Registration)(?:\s+No)?[:.\s]*([A-Z0-9\s\-]{5,15})', re.I)
PHONE_GENERIC = re.compile(r'(\+?\(?\d{2,4}\)?[\s\.-]?\d{3,4}[\s\.-]?\d{3,4})')
EMAIL_GENERIC = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Specific for Australian Licenses (e.g., Arctick AU12345)
ARCTICK_RE = re.compile(r'\b(AU\d{5})\b', re.I)


def find_abn(text: str) -> str:
    """Finds 11-digit ABN in text."""
    match = ABN_PATTERN.search(text)
    return match.group(0).replace(" ", "") if match else None


def find_owner(about_text: str) -> str:
    """Heuristically extracts owner name from 'About' sections."""
    if not about_text: return None
    # Patterns: "Owned by X", "Run by X", "Director X"
    patterns = [
        r'owned\s+and\s+operated\s+by\s+([^,.\n]+)',
        r'founded\s+by\s+([^,.\n]+)',
        r'director\s+([^,.\n]+)',
        r'manager\s+([^,.\n]+)',
    ]
    for p in patterns:
        m = re.search(p, about_text, re.I)
        if m:
            name = m.group(1).strip()
            # Clean up (e.g. "members of the Prietto family" -> skip certain words)
            return name[:50]
    return None


# ─── JSON-LD Extraction ──────────────────────────────────────────────────────

def extract_json_ld(soup: BeautifulSoup) -> list:
    """Extracts structured data from JSON-LD scripts if available."""
    data = []
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            if script.string:
                content = json.loads(script.string)
                if isinstance(content, list):
                    data.extend(content)
                else:
                    data.append(content)
        except json.JSONDecodeError:
            parsing_log.warning("JSON-LD found but could not be parsed.")
        except Exception as e:
            parsing_log.error(f"Error parsing JSON-LD: {e}")
    return data


# ─── Title Extraction ─────────────────────────────────────────────────────────

def extract_title(soup: BeautifulSoup) -> str:
    """Finds the main title using multiple strategies."""
    # Strategy 1: h1
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(separator=" ", strip=True)
        if text and len(text) > 2:
            return text

    # Strategy 2: itemprop
    prop = soup.find(attrs={"itemprop": "name"})
    if prop:
        text = prop.get_text(separator=" ", strip=True)
        if text:
            return text

    # Strategy 3: og:title meta
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()

    # Strategy 4: <title> tag
    if soup.title and soup.title.string:
        return soup.title.string.strip()

    return None


# ─── Price Extraction ─────────────────────────────────────────────────────────

PRICE_CLASSES = [
    "price", "a-price-whole", "a-price", "sale-price",
    "current-price", "offer-price", "product-price",
    "prc-dsc", "discounted-price", "selling-price",
    "Nx9bqj",  # Flipkart's obfuscated class (may change)
    "CxhGGd",  # Flipkart alt class
]

CURRENCY_PATTERN = re.compile(r'[\$₹€£¥]\s*[\d,]+(?:\.\d{1,2})?|[\d,]+(?:\.\d{1,2})?\s*(?:USD|INR|EUR|GBP)')


def extract_price(soup: BeautifulSoup) -> str:
    """Extracts pricing using heuristic class matching and regex."""
    # 1. Try known price classes
    for cls in PRICE_CLASSES:
        found = soup.find(class_=re.compile(re.escape(cls), re.I))
        if found:
            text = found.get_text(separator=" ", strip=True)
            if text and re.search(r'\d', text):
                return text

    # 2. itemprop="price"
    prop = soup.find(attrs={"itemprop": "price"})
    if prop:
        return prop.get("content", prop.get_text(strip=True))

    # 3. Regex scan of short elements
    for el in soup.find_all(['span', 'div', 'p', 'strong', 'b']):
        text = el.get_text(separator=" ", strip=True)
        if len(text) < 35:
            match = CURRENCY_PATTERN.search(text)
            if match:
                return text

    return None


# ─── Rating Extraction ────────────────────────────────────────────────────────

RATING_PATTERN = re.compile(r'(\d[\.\d]*)\s*(?:out of|\/)\s*\d')


def extract_ratings(soup: BeautifulSoup) -> str:
    """Extracts rating via known patterns and class heuristics."""
    # 1. Class-based search
    for el in soup.find_all(class_=re.compile(r'rating|star|review', re.I)):
        text = el.get_text(separator=" ", strip=True)
        if text and re.search(r'\d', text) and len(text) < 50:
            return text

    # 2. itemprop
    prop = soup.find(attrs={"itemprop": "ratingValue"})
    if prop:
        return prop.get("content", prop.get_text(strip=True))

    # 3. Regex
    for el in soup.find_all(['span', 'div', 'i']):
        text = el.get_text(separator=" ", strip=True)
        if len(text) < 40:
            match = RATING_PATTERN.search(text)
            if match:
                return match.group(0)

    return None


# ─── Description Extraction ───────────────────────────────────────────────────

def extract_description(soup: BeautifulSoup) -> str:
    """Extracts product/page description."""
    # itemprop
    prop = soup.find(attrs={"itemprop": "description"})
    if prop:
        text = prop.get_text(separator=" ", strip=True)
        if text:
            return text[:500]

    # og:description
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        return og["content"].strip()[:500]

    # meta description
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return meta["content"].strip()[:500]

    return None


# ─── Image Extraction ─────────────────────────────────────────────────────────

def extract_images(soup: BeautifulSoup, base_url: str = "") -> list:
    """Extracts product/content images (skips icons and tiny images)."""
    images = []
    seen = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy")
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = urljoin(base_url, src)

        # Skip tiny icons, base64, and tracking pixels
        if "data:image" in src or "1x1" in src or "pixel" in src:
            continue
        if src in seen:
            continue
        seen.add(src)

        alt = img.get("alt", "").strip()
        images.append({"Alt": alt, "URL": src})

    return images[:10]  # Top 10


# ─── Link Extraction ──────────────────────────────────────────────────────────

def extract_links(soup: BeautifulSoup, base_url: str = "") -> list:
    """Extracts important links, deduplicates."""
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a['href']
        if href.startswith("/") and not href.startswith("//"):
            href = urljoin(base_url, href)
        elif href.startswith("//"):
            href = "https:" + href

        text = a.get_text(separator=" ", strip=True)
        if text and href and href.startswith("http") and href not in seen:
            seen.add(href)
            links.append({"Text": text[:80], "URL": href})

    return links[:20]


# ─── Heading Extraction ──────────────────────────────────────────────────────

def extract_headings(soup: BeautifulSoup) -> list:
    """Extracts all headings (h1-h3) to understand page structure."""
    headings = []
    for tag in ['h1', 'h2', 'h3']:
        for h in soup.find_all(tag):
            txt = h.get_text(separator=" ", strip=True)
            if txt and len(txt) < 150:
                headings.append({"Level": tag.upper(), "Text": txt})
    return headings


# ─── Discovery Engine (Categories / Services) ─────────────────────────────────

def discover_content_clusters(soup: BeautifulSoup, base_url: str = "") -> list:
    """
    Intelligently discovers clusters of links that likely represent services or categories.
    Uses structural repetition and keyword analysis.
    """
    general_log.info("Running Discovery Engine for services/categories...")
    clusters = []
    seen_links = set()

    # Strategy 1: Find lists (ul/ol) containing many links
    for list_tag in soup.find_all(['ul', 'ol', 'nav']):
        links = list_tag.find_all('a', href=True)
        if 4 <= len(links) <= 100:
            cluster_items = []
            for a in links:
                href = urljoin(base_url, a['href'])
                text = a.get_text(separator=" ", strip=True)
                if text and 2 < len(text) < 60 and href not in seen_links:
                    cluster_items.append({"Name": text, "URL": href})
                    seen_links.add(href)
            
            if len(cluster_items) >= 4:
                prev_h = list_tag.find_previous(['h1', 'h2', 'h3', 'h4', 'strong'])
                context = prev_h.get_text(strip=True) if prev_h else "General"
                clusters.append({"Category": context, "Items": cluster_items})

    # Strategy 2: Find div blocks with repeated link patterns (Grid discovery)
    for div in soup.find_all('div'):
        immediate_links = div.find_all('a', recursive=False)
        if not immediate_links:
            # Try one level deeper
            immediate_links = [a for child in div.find_all(recursive=False) for a in child.find_all('a', recursive=False)]
        
        if 5 <= len(immediate_links) <= 50:
            cluster_items = []
            for a in immediate_links:
                href = urljoin(base_url, a['href'])
                text = a.get_text(separator=" ", strip=True)
                if text and 2 < len(text) < 60 and href not in seen_links:
                    cluster_items.append({"Name": text, "URL": href})
                    seen_links.add(href)
            
            if len(cluster_items) >= 5:
                prev_h = div.find_previous(['h1', 'h2', 'h3', 'strong'])
                context = prev_h.get_text(strip=True) if prev_h else "Discovery"
                clusters.append({"Category": context, "Items": cluster_items})

    return clusters


# ─── Price Decomposition ──────────────────────────────────────────────────────

PRICE_AMOUNT_RE = re.compile(r'[₹$€£¥]\s*([\d,]+(?:\.\d{1,2})?)')
DISCOUNT_RE = re.compile(r'(\d+)\s*%\s*off', re.I)


def decompose_price(raw_price: str) -> dict:
    """
    Splits a raw price string like '₹283 ₹498 43% off' into:
      Sale Price, Original Price, Discount (%)
    Handles Flipkart quirks where text gets concatenated (e.g., '₹49843% off').
    """
    result = {"Sale Price": "", "Original Price": "", "Discount (%)": ""}
    if not raw_price:
        return result

    # 1. First extract discount percentage (before it pollutes price parsing)
    discount_match = DISCOUNT_RE.search(raw_price)
    if discount_match:
        result["Discount (%)"] = discount_match.group(1) + "%"
        discount_val = discount_match.group(1)
    else:
        discount_val = None

    # 2. Clean: insert spaces before currency symbols to separate concatenated values
    cleaned = re.sub(r'([₹$€£¥])', r' \1', raw_price)
    # Also insert space before "% off" pattern to separate from numbers
    cleaned = re.sub(r'(\d)(%\s*off)', r'\1 \2', cleaned, flags=re.I)

    # 3. Find all currency amounts
    amounts = PRICE_AMOUNT_RE.findall(cleaned)

    if amounts:
        # If discount was found and we only have one amount, the original price
        # might have been concatenated with the discount number.
        # E.g., raw = "₹498 43% off" extracted as amounts=["498"] but
        #        raw = "₹49843% off" extracted as amounts=["49843"]
        # In the second case, we need to split "49843" => "498" + "43"
        if len(amounts) == 1 and discount_val:
            full_num = amounts[0].replace(",", "")
            # Check if this number ends with the discount value
            if full_num.endswith(discount_val) and len(full_num) > len(discount_val):
                orig_price = full_num[:len(full_num) - len(discount_val)]
                result["Original Price"] = "₹" + orig_price
                # This was probably the original price, not sale price
                # Sale price should have been a separate element
            else:
                result["Sale Price"] = "₹" + full_num

        elif len(amounts) >= 2:
            sale = amounts[0].replace(",", "")
            orig = amounts[1].replace(",", "")

            # Check if orig is concatenated with discount (e.g., "49843" from "₹498 43%")
            if discount_val and orig.endswith(discount_val) and len(orig) > len(discount_val):
                orig = orig[:len(orig) - len(discount_val)]

            result["Sale Price"] = "₹" + sale
            result["Original Price"] = "₹" + orig

        else:
            result["Sale Price"] = "₹" + amounts[0].replace(",", "")

    return result


# ─── Brand Extraction ─────────────────────────────────────────────────────────

KNOWN_BRANDS = [
    "Mamaearth", "NIVEA", "GARNIER", "Pilgrim", "Dot & Key", "Dot.net",
    "LOTUS HERBALS", "Lotus", "Foxtale", "DENVER", "Joy", "MUUCHSTAC",
    "Dermatouch", "The Derma Co", "Dr. Sheth's", "Chemist at Play",
    "Plix", "The Plant Fix", "ETHIGLO", "RAAGA", "Renee", "Reginald",
    "FOZZBY", "Aroma Magic", "Charwee", "Prinuki", "Ghar Soaps",
    "Cetaphil", "L'Oreal", "Neutrogena", "Olay", "Biotique", "VLCC",
    "Himalaya", "Lakme", "Pond's", "Dove", "Vaseline", "Plum", "WOW",
    "Minimalist", "Mcaffeine", "mCaffeine", "Bella Vita", "YES GLOW",
    "Samsung", "Apple", "OnePlus", "Xiaomi", "Realme", "ASUS", "HP",
    "Dell", "Lenovo", "Boat", "Nike", "Adidas", "Puma",
]


def extract_brand(product_name: str) -> str:
    """Extracts brand from the product name by matching known brands or taking the first word."""
    if not product_name:
        return ""

    # 1. Match known brands (case-insensitive)
    name_lower = product_name.lower()
    for brand in KNOWN_BRANDS:
        if brand.lower() in name_lower:
            return brand

    # 2. Fallback: first word (often the brand in e-commerce titles)
    first_word = product_name.split()[0] if product_name.split() else ""
    # Only use if it looks like a brand (capitalized, not a common word)
    common_words = {"buy", "new", "best", "top", "the", "for", "with", "pack", "set", "combo"}
    if first_word.lower() not in common_words and len(first_word) > 1:
        return first_word

    return ""


# ─── Product Card Extraction (E-Commerce) ─────────────────────────────────────

def extract_product_cards(soup: BeautifulSoup, base_url: str = "") -> list:
    """
    Extracts product cards from listing pages with professional, granular field mapping.
    Each product contains: Product Name, Brand, Sale Price, Original Price, Discount (%),
    Rating, Product URL, Image URL.
    """
    general_log.info("Attempting product card extraction...")
    products = []

    # 1. Identify the 'Main' content area to avoid footer/nav noise
    main_content = (
        soup.find('main') or 
        soup.find(id=re.compile(r'main|content|context', re.I)) or
        soup.find(class_=re.compile(r'main|content|listing-container', re.I)) or
        soup
    )
    
    # 2. Exclude known noise from main_content
    for noise in main_content.find_all(['nav', 'footer', 'header']):
        noise.decompose()

    card_candidates = []
    container_selectors = [
        "a[class*='e15hy9qi0']",    # Hipages listing link-box
        "div[class*='e15hy9qi0']",  # Hipages listing box
        "div[class*='e100q6ld']",   # Hipages alternate
        "div[class*='Listing']",     # Generic / Hipages
        "div[class*='Card']",        # Generic
        "div.MuiBox-root",           # Material UI common card base
        "div[data-testid*='Listing']",
        "article",                   # Semantic card
        "li.product",                # Generic
    ]

    for sel in container_selectors:
        try:
            cards = main_content.select(sel)
            if cards:
                # If it's a high-signal selector (contains 'Listing' or 'Card'),
                # we accept even 1 or 2 items (niche categories).
                is_high_signal = any(word in sel.lower() for word in ['listing', 'card', 'e15hy9qi0', 'e100q6ld', 'mui'])
                if len(cards) >= (1 if is_high_signal else 3):
                    card_candidates.append((sel, cards))
        except Exception:
            continue

    if not card_candidates:
        general_log.info("No repeated listing cards found.")
        return products

    # ── Selection: High Signal vs Discovery ──
    def score_candidate(cand):
        sel, items = cand
        # Base signal: listing/card/hipages specific classes
        signal = 1
        if any(w in sel.lower() for w in ['listing', 'card', 'e15hy9qi', 'e100q6ld']): signal = 5
        elif 'mui' in sel.lower(): signal = 2
        
        # Reward items that are central (fewer items in cluster often means main listings vs huge navigation list)
        if len(items) <= 25: signal += 2
        else: signal -= 2 # Penalize giant footer clusters
        
        # Reward items that look like real business cards (have ratings, chips, or multiple lines)
        sample_card = items[0]
        if sample_card.find(class_=re.compile(r'rating|star|XQDdHH', re.I)): signal += 3
        if sample_card.find(class_=re.compile(r'chip|label|tag|verify', re.I)): signal += 1
        
        return signal

    # ── Final Processing: Collect and Expand ──
    final_cards = []
    seen_card_texts = set()

    # Sort all candidates by signal and then by count
    card_candidates.sort(key=score_candidate, reverse=True)
    
    # Threshold: take everything with signal >= 1
    for sel, cards in card_candidates:
        sig = score_candidate((sel, cards))
        if sig < 1: continue
        
        # If we already have a lot of items (like 20+), maybe skip footer-grade clusters
        if sig == 1 and len(final_cards) > 10:
            continue

        for idx, card in enumerate(cards, 1):
            # Extract basic info
            txt = card.get_text(strip=True)[:100]
            if not txt or txt in seen_card_texts: continue
            seen_card_texts.add(txt)
            
            product = {"#": len(final_cards) + 1}

            # ── Product Name ──
            title_el = (
                card.find("a", attrs={"title": True}) or
                card.find(class_=re.compile(r'title|name|product.?name', re.I)) or
                card.find(["h2", "h3", "h4"]) or
                card.find("a")
            )
            raw_name = ""
            if title_el:
                raw_name = (
                    title_el.get("title") or
                    title_el.get_text(separator=" ", strip=True)
                )[:150]
            product["Product Name"] = raw_name

            # ── Brand ──
            product["Brand"] = extract_brand(raw_name)

            # ── Price ──
            sale_price = ""
            original_price = ""
            discount_pct = ""

            price_spans = []
            for span in card.find_all(['span', 'div'], recursive=True):
                text = span.get_text(strip=True)
                children_with_price = [c for c in span.find_all(['span', 'div']) if '₹' in c.get_text(strip=True)]
                is_leaf = len(children_with_price) == 0
                if is_leaf and CURRENCY_PATTERN.search(text) and len(text) < 25:
                    price_spans.append(text)
                if is_leaf and not discount_pct:
                    disc_match = re.search(r'(\d+)\s*%\s*off', text, re.I)
                    if disc_match:
                        discount_pct = disc_match.group(1) + "%"

            if len(price_spans) >= 2:
                sale_price = price_spans[0]
                original_price = price_spans[1]
            elif len(price_spans) == 1:
                sale_price = price_spans[0]

            if not sale_price:
                price_el = card.find(class_=re.compile(r'price|prc|Nx9bqj|CxhGGd', re.I))
                if price_el:
                    parts = decompose_price(price_el.get_text(separator=" ", strip=True))
                    sale_price = parts["Sale Price"]
                    original_price = parts["Original Price"]
                    discount_pct = parts["Discount (%)"]

            product["Sale Price"] = sale_price
            product["Original Price"] = original_price
            product["Discount (%)"] = discount_pct

            # ── Rating ──
            rating_el = card.find(class_=re.compile(r'rating|star|XQDdHH', re.I))
            product["Rating"] = rating_el.get_text(separator=" ", strip=True) if rating_el else ""

            # ── Product URL ──
            link_el = card.find("a", href=True)
            if link_el:
                href = link_el["href"]
                if href.startswith("/"):
                    href = urljoin(base_url, href)
                product["Product URL"] = href
            else:
                product["Product URL"] = ""

            # ── Image URL ──
            img_el = card.find("img")
            if img_el:
                product["Image URL"] = img_el.get("src") or img_el.get("data-src") or ""
            else:
                product["Image URL"] = ""

            if product.get("Product Name"):
                final_cards.append(product)

    general_log.info(f"Extracted {len(final_cards)} total listing items.")
    return final_cards


# ─── Profile Extraction (Detail Mode) ────────────────────────────────────────

def extract_profile_data(soup: BeautifulSoup, target_url: str = "") -> dict:
    """
    Orchestrates deep extraction of a single business profile.
    Returns raw data mapped to the final JSON schema.
    """
    general_log.info("Starting deep business profile extraction...")
    profile = {}

    # Extract Page Title / Name
    name = soup.find("h1").get_text(strip=True) if soup.find("h1") else extract_title(soup)
    profile["name"] = name

    # About / Description
    about = extract_description(soup)
    profile["about"] = about
    profile["owner"] = find_owner(about)

    # Verification / Rating
    profile["verified"] = bool(soup.find(string=re.compile(r'verified', re.I))) or "Verified" in str(soup)
    profile["rating"] = extract_ratings(soup)

    # Contact (Phone/Email)
    text_content = soup.get_text(separator=" ")
    profile["phone"] = PHONE_GENERIC.search(text_content).group(0) if PHONE_GENERIC.search(text_content) else None
    profile["email"] = EMAIL_GENERIC.search(text_content).group(0) if EMAIL_GENERIC.search(text_content) else None

    # Established
    est_match = re.search(r'(?:established|since|founded)\s*(?:in\s*)?([12]\d{3})', text_content, re.I)
    profile["established"] = int(est_match.group(1)) if est_match else None

    # Services
    services_set = set()
    srv_headings = soup.find_all(re.compile(r'^h[2-5]$'), string=re.compile(r'services|specialties|what we do|categories', re.I))
    for h in srv_headings:
        next_ul = h.find_next_sibling('ul') or h.find_next('ul')
        if next_ul:
            for li in next_ul.find_all('li'):
                txt = li.get_text(strip=True)
                if txt and len(txt) < 80:
                    services_set.add(txt)
    # Fallback to looking for class name indicating services
    if not services_set:
        for el in soup.find_all(class_=re.compile(r'service-item|category-item', re.I)):
            txt = el.get_text(strip=True)
            if txt and len(txt) < 60:
                services_set.add(txt)
    profile["services"] = list(services_set)

    # Location
    profile["address"] = None # Placeholder for smarter detection below
    profile["city"] = None
    profile["postcode"] = None

    # Look for Address patterns (e.g. 123 Street, Suburb, State Postcode)
    addr_match = re.search(r'(\d+[^,\n]+,\s*[^,\n]+,\s*[A-Z]{2,3}\s*(\d{4}))', text_content)
    if addr_match:
        profile["address"] = addr_match.group(1).strip()
        profile["postcode"] = addr_match.group(2)

    # Media (Logo + Gallery)
    images = extract_images(soup, base_url=target_url)
    profile["logo"] = images[0]["URL"] if images else None
    profile["gallery"] = [img["URL"] for img in images[1:10]]

    # Credentials (ABN + Licenses)
    profile["abn"] = find_abn(text_content)
    
    licenses = {}
    lic_matches = LICENSE_PATTERN.findall(text_content)
    # Filter and deduplicate
    for l in lic_matches:
        if l and len(l) > 3:
            licenses[f"license_{len(licenses)+1}"] = l.strip()
    
    # Specific Arctick
    arctick = ARCTICK_RE.search(text_content)
    if arctick:
        licenses["arctick"] = arctick.group(1)
        
    profile["licenses"] = licenses

    # Reviews
    profile["reviews"] = []
    # Heuristic: find nodes with names, dates, and review text
    # Often structured as div > span(name), span(date), p(text)
    review_blocks = soup.find_all(class_=re.compile(r'review|comment|testimonial', re.I))
    for block in review_blocks[:5]: # Take top 5
        rev = {
            "name": None,
            "location": None,
            "date": None,
            "comment": block.get_text(strip=True)[:200]
        }
        # Try to find specific parts inside block
        name_el = block.find(class_=re.compile(r'author|user|name', re.I))
        if name_el: rev["name"] = name_el.get_text(strip=True)
        
        date_el = block.find(class_=re.compile(r'date|timestamp', re.I))
        if date_el: rev["date"] = date_el.get_text(strip=True)
        
        profile["reviews"].append(rev)

    return profile


# ─── Business Profile Link Extraction (Multi-Level) ─────────────────────────

def extract_business_profile_urls(soup: BeautifulSoup, target_url: str) -> list:
    """Extracts valid business/profile links while ignoring noise."""
    from urllib.parse import urlparse, urljoin
    
    main_content = (
        soup.find('main') or 
        soup.find(id=re.compile(r'main|content|context', re.I)) or
        soup.find(class_=re.compile(r'main|content|listing-container', re.I)) or
        soup
    )
    urls = []
    seen = set()
    noise_keywords = [
        "/faq", "/login", "/signup", "/contact", "/terms", "/privacy", 
        "/about", "support", "help", "/categories", "/directory", "/search"
    ]
    
    for a in main_content.find_all("a", href=True):
        parents = [p.name for p in a.parents]
        if 'nav' in parents or 'footer' in parents or 'header' in parents:
            continue
            
        href = a['href']
        if href.startswith("/"):
            href = urljoin(target_url, href)
            
        lower_href = href.lower()
        if not lower_href.startswith("http"): continue
        
        if any(x in lower_href for x in noise_keywords):
            continue
            
        if "hipages.com.au" in target_url:
            if "/find/" in lower_href or "article" in lower_href:
                continue
            if "/connect/" not in lower_href and "/tradie/" not in lower_href:
                continue

        path_parts = [p for p in urlparse(href).path.split("/") if p]
        if len(path_parts) == 0: continue
        
        if href not in seen:
            urls.append(href)
            seen.add(href)
            
    return urls


# ─── Main Parse Entry Point ──────────────────────────────────────────────────

def parse_data(html: str, target_url: str = "", mode: str = "listing") -> dict:
    """
    Entry point for parsing. Supports 'listing' or 'profile' modes.
    """
    general_log.info(f"Parsing HTML ({len(html)} bytes) in {mode} mode...")
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        if mode == "profile":
            return extract_profile_data(soup, target_url=target_url)

        # Standard Listing Data Extraction (existing)
        # Extract single-page level data
        json_ld = extract_json_ld(soup)
        title = extract_title(soup)
        price = extract_price(soup)
        rating = extract_ratings(soup)

        # Fallback from JSON-LD
        if json_ld:
            for item in json_ld:
                if isinstance(item, dict):
                    if not title and "name" in item:
                        title = str(item["name"])
                    if not price and "offers" in item:
                        offers = item["offers"]
                        if isinstance(offers, dict) and "price" in offers:
                            price = str(offers["price"])
                        elif isinstance(offers, list) and offers:
                            price = str(offers[0].get("price", ""))

        data = {
            "URL": target_url,
            "Page Title": title,
            "Price": price,
            "Rating": rating,
            "Description": extract_description(soup),
            "Headings": extract_headings(soup),
            "Images": extract_images(soup, base_url=target_url),
            "Top_Links": extract_links(soup, base_url=target_url),
            "JSON_LD": json_ld,
            "Products": extract_product_cards(soup, base_url=target_url),
            "Discovered_Items": discover_content_clusters(soup, base_url=target_url),
            "Profile_Links": extract_business_profile_urls(soup, target_url=target_url),
        }

        return data

    except Exception as e:
        parsing_log.error(f"Fatal parsing error: {e}")
        return {"URL": target_url, "Error": str(e)}
