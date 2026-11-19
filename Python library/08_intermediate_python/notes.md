# Intermediate Python

## Goal
Write more efficient, expressive, and Pythonic code using advanced built-in features.

---

## Topics
- iterators
- generators
- decorators
- context managers
- unpacking (* and **)
- enumerate / zip / any / all
- collections module
- itertools
- functools
- regex

---

## What you should know after this section

- understand lazy evaluation (generators)
- write cleaner loops with enumerate/zip
- modify function behavior with decorators
- manage resources with context managers
- use powerful standard library tools
- write concise and readable code

---

## Key concepts

### Iterator
- object you can loop over
- uses __iter__ and __next__

### Generator
- function that yields values one by one
- memory efficient

### Decorator
- function that wraps another function

### Context manager
- manages setup and cleanup (with statement)

---

## Common mistakes

- using generators when list is needed (or vice versa)
- overcomplicating decorators
- forgetting to consume iterators
- writing unreadable one-liners
- not understanding lazy evaluation

---

## Suggested order

1. 01_iterators.py
2. 02_generators.py
3. 03_decorators.py
4. 04_context_managers.py
5. 05_unpacking.py
6. 06_enumerate_zip_any_all.py
7. 07_collections_module.py
8. 08_itertools.py
9. 09_functools.py
10. 10_regex.py