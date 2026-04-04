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
    
    # Deep copy/init from schema
    clean = {
        "business": {
            "name": normalize_text(raw_profile.get("name")) or "",
            "owner": normalize_text(raw_profile.get("owner")) or "",
            "established": raw_profile.get("established"),
            "rating": raw_profile.get("rating"),
            "verified": raw_profile.get("verified"),
        },
        "contact": {
            "phone": normalize_text(raw_profile.get("phone")) or "",
            "email": normalize_text(raw_profile.get("email")) or None,
        },
        "location": {
            "address": normalize_text(raw_profile.get("address")) or "",
            "city": normalize_text(raw_profile.get("city")) or "",
            "postcode": normalize_text(raw_profile.get("postcode")) or "",
        },
        "credentials": {
            "abn": normalize_text(raw_profile.get("abn")) or "",
            "licenses": raw_profile.get("licenses", {}) or {},
        },
        "services": raw_profile.get("services", []) or [],
        "about": normalize_text(raw_profile.get("about")) or "",
        "media": {
            "logo": raw_profile.get("logo") or "",
            "gallery": raw_profile.get("gallery", []) or [],
        },
        "reviews": [],
    }

    # Clean reviews
    for rev in raw_profile.get("reviews", []):
        clean["reviews"].append({
            "name": normalize_text(rev.get("name")) or "",
            "location": normalize_text(rev.get("location")) or "",
            "date": normalize_text(rev.get("date")) or "",
            "comment": normalize_text(rev.get("comment")) or "",
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
        name = normalize_text(product.get("Product Name"))
        if not name or name in seen_names:
            continue
        seen_names.add(name)

        cleaned = {
            "#": counter,
            "Product Name": name,
            "Brand": normalize_text(product.get("Brand")) or "—",
            "Sale Price": normalize_price(product.get("Sale Price")) or "—",
            "Original Price": normalize_price(product.get("Original Price")) or "—",
            "Discount (%)": normalize_text(product.get("Discount (%)")) or "—",
            "Rating": normalize_text(product.get("Rating")) or "—",
            "Product URL": product.get("Product URL", ""),
            "Image URL": product.get("Image URL", ""),
        }
        cleaned_products.append(cleaned)
        counter += 1

    # 2. Process discovered services/categories
    for cluster in raw_discovery:
        category = normalize_text(cluster.get("Category", "General"))
        for item in cluster.get("Items", []):
            name = normalize_text(item.get("Name"))
            if not name or name in seen_names:
                continue
            seen_names.add(name)

            cleaned = {
                "#": counter,
                "Product Name": name,
                "Brand": category,
                "Sale Price": "Service / Category",
                "Original Price": "—",
                "Discount (%)": "—",
                "Rating": "—",
                "Product URL": item.get("URL", ""),
                "Image URL": "—",
            }
            cleaned_products.append(cleaned)
            counter += 1

    if not cleaned_products:
        general_log.info("No repeated items or categories found.")

    if summary.get("Page Title") == "Unknown Title":
        validation_log.warning(f"Missing Page Title for {summary['URL']}")

    general_log.info(f"Cleaning complete: {len(cleaned_products)} items, summary ready.")
    return {"summary": summary, "products": cleaned_products}
