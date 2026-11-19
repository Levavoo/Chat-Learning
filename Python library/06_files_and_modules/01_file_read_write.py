"""
Topic: File Read/Write
Goal: Work with text files
Level: Beginner
"""

# Write file (overwrite)
with open("example.txt", "w") as f:
    f.write("Hello World\n")
    f.write("Second line")

# Read file
with open("example.txt", "r") as f:
    content = f.read()
    print(content)

# Output:
# Hello World
# Second line

# Read line by line
with open("example.txt", "r") as f:
    for line in f:
        print(line.strip())

# Append
with open("example.txt", "a") as f:
    f.write("\nAppended line")

# Pitfall: "w" deletes existing content