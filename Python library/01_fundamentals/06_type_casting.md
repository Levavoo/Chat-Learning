---
type: learnpaper
kind: concept
domain: programming
technology: Python
chapter: 01_fundamentals
level: beginner
status: draft
tags: [python, fundamentals, type-conversion]
---

# Type Conversion

> **In one sentence:** Type conversion creates a value of another type, such as turning numeric text into an integer with `int()`.

## Learning objectives

- Convert between `str`, `int`, `float` and `bool`.
- Explain the difference between conversion and validation.
- Handle invalid conversions safely.

## Why it matters

Data from user input, CSV files and external APIs often arrive as strings or other generic types. Converting to the expected representation is essential before calculations and comparisons.

## Worked example

```python
raw_quantity = " 12 "
quantity = int(raw_quantity)
price = 2.50
print(quantity * price)  # 30.0
print(str(quantity))      # 12
```

**Walkthrough:** `int()` accepts surrounding whitespace in this numeric string and produces an integer; multiplication with `float` produces a floating-point result; `str()` converts the integer to displayable text.

## Core conversions

| Conversion | Example | Result |
| --- | --- | --- |
| `int("42")` | Numeric text to integer | `42` |
| `float("2.5")` | Numeric text to float | `2.5` |
| `str(42)` | Number to string | `"42"` |
| `bool(0)` | Zero to bool | `False` |
| `bool("False")` | Nonempty text to bool | `True` |

## Common failures

```python
try:
    count = int("twelve")
except ValueError:
    count = 0
print(count)  # 0
```

The example uses a fallback for demonstration; in a real application you may instead ask the user to correct the value or reject the request. Do not silently replace invalid data without an explicit policy.

## Conversion vs validation

`int(text)` attempts conversion; `text.isdigit()` is **not** a complete integer validator: negative signs and other accepted forms may not pass. A guarded `try`/`except ValueError` often expresses the intent better.

## Try it

**Predict:** What does `bool("0")` return?

**Challenge:** Parse two input strings as integers, add them, and return a friendly message if either conversion fails.

**Code reference:** [06_type_casting.py](06_type_casting.py).

## Practice and self-check

- [ ] Explain the idea aloud without reading the note.
- [ ] Run the linked Python script, then predict the output after changing one input.
- [ ] Recreate the example from memory.
- [ ] Complete the challenge above and explain your solution.

## Connections and reference

- Chapter: [[01_fundamentals/README|Fundamentals chapter]]
- Previous: [[05_input_output]]
- [Python tutorial — official documentation](https://docs.python.org/3/tutorial/)

*Learning status: draft — complete the self-check before marking this note mastered.*
