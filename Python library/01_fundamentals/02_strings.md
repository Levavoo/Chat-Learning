---
type: learnpaper
kind: concept
domain: programming
technology: Python
chapter: 01_fundamentals
level: beginner
status: draft
tags: [python, fundamentals, strings]
---

# Strings

> **In one sentence:** A string (`str`) is an immutable sequence of Unicode characters used to represent text.

## Learning objectives

- Index and slice a string, including negative indexes.
- Explain why strings cannot be changed in place.
- Clean and combine text with methods and f-strings.

## Why it matters

Names, chat messages, file paths and API fields are often represented as text. String operations help format, validate and transform them.

## Mental model

For `text = "Python"`, indexes run from `0` to `5`; negative indexes count backward. A slice `text[start:stop]` includes `start` but **excludes** `stop`.

```mermaid
flowchart LR
    S["Python"] --> I[Index 0: P]
    S --> R[Slice 1:4 = "yth"]
```

## Worked example

```python
text = "  Ada Lovelace  "
clean = text.strip()
first = clean[:3]
print(first)               # Ada
print(clean.upper())       # ADA LOVELACE
print(f"Hello, {first}!") # Hello, Ada!
```

**Walkthrough:** `strip()` returns a new string without surrounding whitespace. `[:3]` selects characters at positions 0–2; `upper()` returns another new string; the f-string inserts `first` into text.

## Important operations

| Operation | Effect |
| --- | --- |
| `s[0]`, `s[-1]` | First, last character |
| `s[1:4]` | Slice (end excluded) |
| `s.split(",")` | Split into a list |
| `"-".join(parts)` | Join strings in a collection |
| `s.replace("a", "b")` | Return modified copy |
| `len(s)` | Count characters |

## Pitfalls

- `s[0] = "X"` raises `TypeError`: strings are immutable.
- `s.strip()` does **not** update `s`; write `s = s.strip()` to rebind it.
- Invalid indexes raise `IndexError`; slices beyond the end are generally permitted.

## Try it

**Predict:** What does `"Python"[-3:]` produce?

**Challenge:** Convert `"  red,green,blue  "` to a list of three cleaned strings, then join with `" | "`.

**Code reference:** [02_strings.py](02_strings.py).

## Practice and self-check

- [ ] Explain the idea aloud without reading the note.
- [ ] Run the linked Python script, then predict the output after changing one input.
- [ ] Recreate the example from memory.
- [ ] Complete the challenge above and explain your solution.

## Connections and reference

- Chapter: [[01_fundamentals/README|Fundamentals chapter]]
- Previous: [[01_variables_types]]
- Next: [[03_numbers]]
- [Python tutorial — official documentation](https://docs.python.org/3/tutorial/)

*Learning status: draft — complete the self-check before marking this note mastered.*
