# 🕷️ Advanced Stealth Web Scraper

Playwright-powered async web scraper with anti-detection, deep extraction, and batch concurrency.

## Quick Start

```bash
# 1. Activate virtual environment
.\venv\Scripts\activate

# 2. Run the scraper
python main.py "https://example.com"
```

## Usage

```bash
# Single URL
python main.py "https://example.com"

# Multiple URLs (comma-separated)
python main.py "https://url1.com,https://url2.com"

# From a file
python main.py urls.txt

# With output format options
python main.py urls.txt --formats json,csv,xlsx

# Run in visible browser mode (default is headless)
python main.py "https://example.com" --headful
```

## Project Structure

```
├── main.py              ← Entry point (run this)
├── requirements.txt     ← Python dependencies
├── scraper/             ← Core scraper modules
│   ├── network.py       ← Async browser & fetch engine
│   ├── parser.py        ← DOM parsing & data extraction
│   ├── cleaner.py       ← Data cleaning & schema enforcement
│   ├── stealth.py       ← Anti-bot stealth patches
│   ├── storage.py       ← Output file writers (JSON/CSV/TXT/XLSX)
│   └── logger.py        ← Logging configuration
├── output/              ← Scraped data files go here
├── .logs/               ← Runtime logs
└── scripts/             ← Debug/test utilities
```

## Features

- **Async Concurrency** — Processes 4 URLs in parallel using async tabs
- **Deep Extraction** — Scans mailto/tel links, JSON-LD, meta tags, Google Maps embeds
- **Anti-Detection** — Stealth patches, random user-agents, human-like mouse movements
- **Strict Schema** — Every field always present; missing data = `null`, never skipped
- **Smart Waits** — Event-driven load detection instead of fixed delays
