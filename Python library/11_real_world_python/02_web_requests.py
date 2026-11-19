"""
Topic: Web Requests
Goal: Fetch data from APIs
"""

import requests

response = requests.get("https://jsonplaceholder.typicode.com/todos/1")

print(response.status_code)
print(response.json())

# Output: JSON data