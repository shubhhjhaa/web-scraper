import re
import pandas as pd
from .logger import validation_log, general_log


def normalize_text(text) -> str:
    """Collapses whitespace and strips."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', str(text)).strip()


def normalize_price(price_text) -> str:
    """Cleans price strings: removes extra spaces, keeps currency symbol."""
    if not price_text:
        return ""
    text = normalize_text(price_text)
    text = re.sub(r'^(from|starting\s+at|mrp)\s*', '', text, flags=re.I)
    return text if text else ""


# ─── Professional Column Schema ──────────────────────────────────────────────
# These are the final column names that appear in all outputs.

PRODUCT_COLUMNS = [
    "#",               # Row number
    "Product Name",    # Full product title
    "Brand",           # Extracted or inferred brand
    "Sale Price",      # Current / discounted price
    "Original Price",  # MRP / original price
    "Discount (%)",    # Discount percentage
    "Rating",          # Star rating if available
    "Product URL",     # Direct link to product page
    "Image URL",       # Product image link
]


# ─── Business Profile Schema ────────────────────────────────────────────────
# This schema is used for single-business detail pages.

PROFILE_SCHEMA = {
    "business": {
        "name": "",
        "owner": "",
        "established": None,
        "rating": None,
        "verified": None
    },
    "contact": {
        "phone": "",
        "email": None
    },
    "location": {
        "address": "",
        "city": "",
        "state": "",
        "postcode": ""
    },
    "credentials": {
        "abn": "",
        "licenses": {}
    },
    "services": [],
    "about": "",
    "media": {
        "logo": "",
        "gallery": []
    },
    "reviews": []
}


def clean_business_profile(raw_profile: dict) -> dict:
    """
    Cleans and structures raw extracted profile data into the strict JSON schema.
    """
    general_log.info("Cleaning business profile data...")
    
    # ── Strict Validation Functions ──
    def strict_phone(val):
        v = normalize_text(val)
        if not v: return None
        # Discard invalid phones
        if len(re.sub(r'\D', '', v)) < 8: return None
        return v

    def strict_email(val):
        v = normalize_text(val)
        if not v: return None
        if "no-reply" in v.lower() or "noreply" in v.lower(): return None
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v): return None
        return v

    def strict_postcode(val):
        v = normalize_text(val)
        if not v: return None
        v_num = re.sub(r'\D', '', v)
        if len(v_num) == 4: return v_num
        return None

    def strict_abn(val):
        v = normalize_text(val)
        if not v: return None
        v_num = re.sub(r'\D', '', v)
        if len(v_num) == 11: return v_num
        return None
        
    def strict_string(val):
        v = normalize_text(val)
        if not v: return None
        vl = v.lower()
        noise = ["faq", "directory", "navigation", "toggle menu", "skip to content"]
        if any(n in vl for n in noise) and len(v) < 30: return None
        return v

    # Deep copy/init from schema with strict validations
    clean = {
        "business": {
            "name": strict_string(raw_profile.get("name")),
            "owner": strict_string(raw_profile.get("owner")),
            "established": raw_profile.get("established"),
            "rating": strict_string(raw_profile.get("rating")),
            "verified": raw_profile.get("verified"),
        },
        "contact": {
            "phone": strict_phone(raw_profile.get("phone")),
            "email": strict_email(raw_profile.get("email")),
        },
        "location": {
            "address": strict_string(raw_profile.get("address")),
            "city": strict_string(raw_profile.get("city")),
            "state": strict_string(raw_profile.get("state")),
            "postcode": strict_postcode(raw_profile.get("postcode")),
        },
        "credentials": {
            "abn": strict_abn(raw_profile.get("abn")),
            "licenses": raw_profile.get("licenses", {}) or {},
        },
        "services": raw_profile.get("services", []) or [],
        "about": strict_string(raw_profile.get("about")),
        "media": {
            "logo": raw_profile.get("logo") or None,
            "gallery": raw_profile.get("gallery", []) or [],
        },
        "reviews": [],
    }

    # Clean reviews
    for rev in raw_profile.get("reviews", []):
        clean["reviews"].append({
            "name": strict_string(rev.get("name")),
            "location": strict_string(rev.get("location")),
            "date": strict_string(rev.get("date")),
            "comment": strict_string(rev.get("comment")),
        })

    return clean


def clean_and_validate(raw_data: dict) -> dict:
    """
    Takes parsed data and returns:
    1. A cleaned page-level summary dict
    2. A cleaned list of product dicts with professional column names

    Returns: {"summary": {...}, "products": [...]}
    """
    general_log.info("Cleaning and validating extracted data...")

    if "Error" in raw_data:
        return {
            "summary": {
                "URL": raw_data.get("URL", ""),
                "Page Title": "Error",
                "Description": "",
                "Error Message": raw_data.get("Error", "Unknown Error"),
            },
            "products": [],
        }

    # ── Page-level summary ──
    summary = {}
    summary["URL"] = raw_data.get("URL", "")
    summary["Page Title"] = normalize_text(raw_data.get("Page Title")) or "Unknown Title"
    summary["Description"] = normalize_text(raw_data.get("Description")) or ""

    headings = raw_data.get("Headings", [])
    if isinstance(headings, list) and headings:
        summary["Headings"] = " | ".join([normalize_text(h) for h in headings if normalize_text(h)])
    else:
        summary["Headings"] = ""

    summary["Has JSON-LD"] = "Yes" if raw_data.get("JSON_LD") else "No"
    summary["Error Message"] = ""

    # ── Product-level cleaning ──
    raw_products = raw_data.get("Products", [])
    raw_discovery = raw_data.get("Discovered_Items", [])
    cleaned_products = []
    seen_names = set()
    counter = 1

    # 1. Process standard cards
    for product in raw_products:
        name = normalize_text(product.get("Product Name")) or None
        if name and name in seen_names:
            continue
        if name:
            seen_names.add(name)

        cleaned = {
            "#": counter,
            "Product Name": name,
            "Brand": normalize_text(product.get("Brand")) or None,
            "Sale Price": normalize_price(product.get("Sale Price")) or None,
            "Original Price": normalize_price(product.get("Original Price")) or None,
            "Discount (%)": normalize_text(product.get("Discount (%)")) or None,
            "Rating": normalize_text(product.get("Rating")) or None,
            "Product URL": product.get("Product URL") or None,
            "Image URL": product.get("Image URL") or None,
        }
        cleaned_products.append(cleaned)
        counter += 1

    # 2. Process discovered services/categories
    for cluster in raw_discovery:
        category = normalize_text(cluster.get("Category", "General"))
        for item in cluster.get("Items", []):
            name = normalize_text(item.get("Name")) or None
            if name and name in seen_names:
                continue
            if name:
                seen_names.add(name)

            cleaned = {
                "#": counter,
                "Product Name": name,
                "Brand": category,
                "Sale Price": "Service / Category",
                "Original Price": None,
                "Discount (%)": None,
                "Rating": None,
                "Product URL": item.get("URL") or None,
                "Image URL": None,
            }
            cleaned_products.append(cleaned)
            counter += 1

    if not cleaned_products:
        general_log.info("No repeated items or categories found.")

    if summary.get("Page Title") == "Unknown Title":
        validation_log.warning(f"Missing Page Title for {summary['URL']}")

    general_log.info(f"Cleaning complete: {len(cleaned_products)} items, summary ready.")
    return {"summary": summary, "products": cleaned_products}
