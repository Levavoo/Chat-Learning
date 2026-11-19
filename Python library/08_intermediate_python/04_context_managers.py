"""
Topic: Context Managers
Goal: Manage resources safely
"""

# Built-in example
with open("file.txt", "w") as f:
    f.write("Hello")

# Custom context manager
class MyContext:
    def __enter__(self):
        print("Enter")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print("Exit")

with MyContext():
    print("Inside")

# Output:
# Enter
# Inside
# Exit