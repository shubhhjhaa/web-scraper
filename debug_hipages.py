from bs4 import BeautifulSoup
import re
from pathlib import Path

html_file = Path('c:/Users/jhak8/Desktop/Scapper/.cache/2b1f0228f449c175363924f536dee62b.html')
if not html_file.exists():
    print(f"File {html_file} not found.")
    exit(1)

html = html_file.read_text(encoding='utf-8')
soup = BeautifulSoup(html, 'html.parser')

print("--- Searching for Jodi & Gordon Contracting NT ---")
target = soup.find(string=re.compile('Jodi & Gordon Contracting NT', re.I))
if target:
    parent = target.parent
    print(f"Parent tag: <{parent.name}> classes: {parent.get('class')}")
    
    # Climb up to find the card container
    # I'll check all ancestors
    for idx, ancestor in enumerate(target.parents):
        if ancestor.name == 'div':
            cls = ancestor.get('class', [])
            print(f"Ancestor {idx} <div class='{cls}'>")
            if idx > 15: break
else:
    print("Not found.")

# Let's see some other potential business names to verify the pattern
print("\n--- Listing potential card titles ---")
for h3 in soup.find_all('h3'):
    print(f"H3: {h3.get_text(strip=True)}")
