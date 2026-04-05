from scraper.parser import extract_product_cards
from bs4 import BeautifulSoup
from pathlib import Path

html_file = Path('c:/Users/jhak8/Desktop/Scapper/.cache/2b1f0228f449c175363924f536dee62b.html')
html = html_file.read_text(encoding='utf-8')
soup = BeautifulSoup(html, 'html.parser')

products = extract_product_cards(soup, 'https://hipages.com.au')
print(f'Found {len(products)} products/listings')
for p in products:
    name = p.get('Product Name', 'Unknown')
    url = p.get('Product URL', 'Unknown')
    print(f"- {name} | {url}")
