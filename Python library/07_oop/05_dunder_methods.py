"""
Topic: Dunder Methods
Goal: Customize object behavior
Level: Intermediate
"""

class Book:
    def __init__(self, title):
        self.title = title

    def __str__(self):
        return f"Book: {self.title}"

    def __len__(self):
        return len(self.title)


b = Book("Python")

print(b)        # Book: Python
print(len(b))   # 6


# Common dunder methods:
# __str__ → user-friendly string
# __repr__ → developer representation
# __len__ → length