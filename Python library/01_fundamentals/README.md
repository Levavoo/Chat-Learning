---
type: chapter-index
kind: concept
domain: programming
technology: Python
chapter: 01_fundamentals
level: beginner
status: learning
tags: [python, fundamentals, navigation]
---

# Chapter 01 — Python Fundamentals

> **Goal:** Understand values, expressions, text, logic, user input and type conversion well enough to build small Python scripts independently.

## Prerequisites

- Python 3.11+ installed, and a terminal or VS Code available.
- If needed, start with [Python installation](../00_setup/python_installation.md).
- Optional: read [[uv_basics|uv basics]] to understand project environments and dependency management.

## Learning path

| Step | Learnpaper | Runnable example | Core skill |
| --- | --- | --- | --- |
| 1 | [[01_variables_types]] | [01_variables_types.py](01_variables_types.py) | Names, objects, types |
| 2 | [[02_strings]] | [02_strings.py](02_strings.py) | Text transformation |
| 3 | [[03_numbers]] | [03_numbers.py](03_numbers.py) | Arithmetic and precision |
| 4 | [[04_booleans]] | [04_booleans.py](04_booleans.py) | Conditions |
| 5 | [[05_input_output]] | [05_input_output.py](05_input_output.py) | Terminal interaction |
| 6 | [[06_type_casting]] | [06_type_casting.py](06_type_casting.py) | Safe conversion |

## Study workflow

1. Open one learnpaper in Obsidian; explain its concept in your own words.
2. Predict the example's output, then run the linked `.py` file in VS Code.
3. Change inputs, deliberately trigger a pitfall and inspect the outcome.
4. Solve the challenge without copying the solution.
5. Check the self-review boxes on the learnpaper and update its `status` property.

## Running examples

From this chapter directory:

```powershell
python 01_variables_types.py
python 02_strings.py
# ...
python 05_input_output.py  # interactive prompts
```

The chapter's existing [notes.md](notes.md) remains as a quick overview. Each learnpaper is the detailed study material.

## Chapter project: CLI Receipt

Build a tiny receipt calculator using only chapter topics. Ask for a product name, quantity and unit price; convert numeric input, calculate a total, and print a formatted receipt. Add a simple eligibility condition (e.g. free shipping when total >= 50).

**Minimum acceptance criteria:**

- Correct use of `str`, `int`, `float`, `bool` and f-strings.
- Output is correct for a normal input.
- Invalid numeric text is handled or clearly reported.
- Can explain why floats aren't ideal for exact financial calculations.

## Completion checklist

- [ ] All six learnpapers read and understood.
- [ ] All six example files executed and modified.
- [ ] Chapter receipt exercise completed.
- [ ] I can explain assignment vs equality, `/ ` vs `//`, string immutability, and `input()` types.

## Navigation

- [[Home|Knowledge home]]
- [Python learning roadmap](../ROADMAP.md)
- Next chapter: [Control Flow](../02_control_flow/notes.md)
