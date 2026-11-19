"""
Topic: Strings
Goal: Understand string creation, indexing, slicing, and common methods
Level: Beginner
"""

text = "Python"

print(text)
# Output: Python

# Indexing
print(text[0])   # Output: P
print(text[1])   # Output: y
print(text[-1])  # Output: n

# Slicing
print(text[0:2])  # Output: Py
print(text[2:])   # Output: thon
print(text[:4])   # Output: Pyth
print(text[::-1]) # Output: nohtyP

# Length
print(len(text))  # Output: 6

# String methods
message = " hello world "

print(message.upper())      # Output:  HELLO WORLD
print(message.lower())      # Output:  hello world
print(message.strip())      # Output: hello world
print(message.replace("world", "Python"))  # Output:  hello Python

# Splitting
sentence = "apple,banana,orange"
fruits = sentence.split(",")
print(fruits)
# Output: ['apple', 'banana', 'orange']

# Joining
joined = " - ".join(fruits)
print(joined)
# Output: apple - banana - orange

# f-strings
name = "Mia"
age = 22
print(f"My name is {name} and I am {age} years old.")
# Output: My name is Mia and I am 22 years old.

# Pitfall: strings are immutable
word = "cat"
# word[0] = "b"   # This would raise an error

# Correct way
word = "b" + word[1:]
print(word)
# Output: bat