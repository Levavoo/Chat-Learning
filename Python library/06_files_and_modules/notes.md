# Files and Modules

## Goal
Read/write data from files and organize code into reusable modules.

---

## Topics
- reading and writing files
- file modes (r, w, a)
- pathlib
- JSON handling
- CSV handling
- imports and modules
- packages

---

## What you should know after this section

- read and write text files
- safely handle files
- work with JSON and CSV data
- organize code into multiple files
- import functions and modules correctly

---

## Key concepts

### File modes
- "r" → read
- "w" → write (overwrite)
- "a" → append

### Context manager
- `with open(...)` automatically closes file

### Modules
- any `.py` file is a module

### Packages
- folder containing multiple modules

---

## Common mistakes

- forgetting to close files
- overwriting files unintentionally
- wrong file paths
- circular imports
- mixing relative and absolute imports incorrectly

---

## Suggested order

1. 01_file_read_write.py
2. 02_pathlib.py
3. 03_json.py
4. 04_csv.py
5. 05_imports_modules.py
6. 06_packages.py