---
type: learnpaper
kind: concept
domain: programming
technology: Python
chapter: 01_fundamentals
level: beginner
status: draft
tags: [python, fundamentals, numbers]
---

# Numbers and Arithmetic

> **In one sentence:** Python uses numeric types such as `int` and `float` for arithmetic; the operator determines the calculation.

## Learning objectives

- Use arithmetic operators including `/`, `//`, `%` and `**`.
- Understand the distinction between integer and floating-point results.
- Recognize floating-point rounding limitations.

## Why it matters

Counts, prices, durations, measurements and ML calculations require numerical operations. Correctly choosing the type and operator avoids subtle bugs.

## Worked example

```python
items = 10
people = 3
print(items / people)   # 3.3333333333333335
print(items // people)  # 3
print(items % people)   # 1
print(2 ** 3)          # 8
```

**Walkthrough:** `/` performs true division, returning a float; `//` rounds the quotient down (toward negative infinity); `%` gives the modulo remainder; `**` raises a value to a power.

## Operator reference

| Operator | Meaning | Example |
| --- | --- | --- |
| `+`, `-`, `*` | Add, subtract, multiply | `2 * 3 == 6` |
| `/` | True division | `4 / 2 == 2.0` |
| `//` | Floor division | `-7 // 3 == -3` |
| `%` | Modulo | `10 % 3 == 1` |
| `**` | Exponentiation | `2 ** 4 == 16` |

## Floating-point mental model

Binary floating-point cannot represent some decimal fractions exactly:

```python
print(0.1 + 0.2 == 0.3)  # False
print(round(0.1 + 0.2, 2))  # 0.3
```

For exact decimal accounting, consider `decimal.Decimal` with carefully constructed decimal strings rather than assuming floats represent currency exactly.

## Pitfalls

- `round()` controls presentation or rounding; it does not make a float mathematically exact.
- `/` produces a float even when division is exact.
- `//` is *floor* division, not always truncation toward zero.
- The existing example's `price + tax` adds a **flat amount**, not a percentage tax rate. For a 20% tax rate use `total = price * (1 + rate)`.

## Try it

**Predict:** What is `-7 // 3`? Why?

**Challenge:** Given 29 items and boxes that hold 6 items, calculate complete boxes and leftover items.

**Code reference:** [03_numbers.py](03_numbers.py).

## Practice and self-check

- [ ] Explain the idea aloud without reading the note.
- [ ] Run the linked Python script, then predict the output after changing one input.
- [ ] Recreate the example from memory.
- [ ] Complete the challenge above and explain your solution.

## Connections and reference

- Chapter: [[01_fundamentals/README|Fundamentals chapter]]
- Previous: [[02_strings]]
- Next: [[04_booleans]]
- [Python tutorial — official documentation](https://docs.python.org/3/tutorial/)

*Learning status: draft — complete the self-check before marking this note mastered.*
