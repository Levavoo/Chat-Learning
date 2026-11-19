"""
Topic: Type Casting
Goal: Convert values between common Python types
Level: Beginner
"""

# String to int
age_text = "25"
age_number = int(age_text)

print(age_number)        # Output: 25
print(type(age_number))  # Output: <class 'int'>

# String to float
price_text = "19.99"
price_number = float(price_text)

print(price_number)        # Output: 19.99
print(type(price_number))  # Output: <class 'float'>

# Number to string
year = 2026
year_text = str(year)

print(year_text)        # Output: 2026
print(type(year_text))  # Output: <class 'str'>

# To boolean
print(bool(0))       # Output: False
print(bool(42))      # Output: True
print(bool(""))      # Output: False
print(bool("hello")) # Output: True

# Combining string and number
name = "Omar"
score = 95

# print("Score: " + score)  # Error
print("Score: " + str(score))
# Output: Score: 95

# Pitfall: invalid conversion
# int("hello")  # This raises ValueError

# Safe example
number_text = "100"
if number_text.isdigit():
    print(int(number_text) + 1)
    # Output: 101