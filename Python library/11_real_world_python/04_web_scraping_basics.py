"""
Topic: Web Scraping
Goal: Extract data from HTML
"""

import requests
from bs4 import BeautifulSoup

url = "https://example.com"
response = requests.get(url)

soup = BeautifulSoup(response.text, "html.parser")

# Example: find all links
for link in soup.find_all("a"):
    print(link.get("href"))

# Note: always check site rules before scraping
