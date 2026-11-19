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

## Mental model: characters, positions, and slices

A string is an **ordered sequence** of characters. Think of each character as having a numbered seat. Python starts counting at **0**, not 1.

For `text = "Python"`:

| Character | P | y | t | h | o | n |
| --- | --- | --- | --- | --- | --- | --- |
| Index from left | 0 | 1 | 2 | 3 | 4 | 5 |
| Index from right | -6 | -5 | -4 | -3 | -2 | -1 |

### 1. Indexing: select one character

```python
text = "Python"
print(text[0])   # P (first character)
print(text[2])   # t (third character)
print(text[-1])  # n (last character)
print(text[-2])  # o (second from the end)
```

**Why does `text[2]` return `t`, rather than `y`?** Because index 0 refers to the first character. Index 2 is the *third* character.

### 2. Slicing: select a range

A slice `text[start:stop]` means:

- **Start at** the character with index `start` (included).
- **Stop before** the character with index `stop` (excluded).
- Create a **new string** containing the selected characters.

```text
Character:     P   y   t   h   o   n
Index:         0   1   2   3   4   5
               |           |
text[1:4]      |   y   t   h   |       -> "yth"
                   ^ start  ^ end boundary
```

```python
text = "Python"
print(text[1:4])  # yth  -> indexes 1, 2, 3
print(text[0:2])  # Py   -> indexes 0, 1
print(text[:3])   # Pyt  -> start defaults to beginning
print(text[3:])   # hon  -> stop defaults to end
print(text[-3:])  # hon  -> last three characters
print(text[:])    # Python -> complete string
```

**Why is `stop` excluded?** It makes the slice length easy to calculate: for a normal forward slice, `stop - start` is the number of selected characters. For example, `4 - 1 = 3` characters in `text[1:4]`.

### 3. Optional third value: step

Slices can also specify how far to move at each step: `text[start:stop:step]`.

```python
print(text[::2])   # Pto   -> every second character
print(text[::-1])  # nohtyP -> reverse the string
```

A negative step moves backward, so default boundaries behave differently than for forward slices.

### 4. What happens with invalid positions?

```python
# text[99]  -> IndexError: single character does not exist
print(text[2:99])  # thon -> slices safely stop at the string's end
print(text[3:3])   # ""   -> empty range
```

**Check your understanding:** Predict `text[1:5:2]` before running it. Which positions are visited?

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
