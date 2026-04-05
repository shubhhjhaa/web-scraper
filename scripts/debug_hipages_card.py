from bs4 import BeautifulSoup
import re
from pathlib import Path

html_file = Path('c:/Users/jhak8/Desktop/Scapper/.cache/2b1f0228f449c175363924f536dee62b.html')
html = html_file.read_text(encoding='utf-8')
soup = BeautifulSoup(html, 'html.parser')

target = soup.find(string=re.compile('Waldron & Gordon', re.I))
if target:
    print('Found text. Parent chain:')
    curr = target.parent # Start from parent
    for i in range(12):
        print(f"{i}: <{curr.name} class='{curr.get('class', [])}'>")
        curr = curr.parent
        if not curr: break
else:
    print('Not found')
