# Project Structure

## Goal

Understand how to organize Python projects.

---

## Minimal structure

```id="sz7g5x"
project/
│
├── .venv/
├── README.md
├── requirements.txt
├── main.py
└── src/
```

---

## Recommended structure (this repo)

```id="l4n6he"
python-reference-repo/
│
├── 00_setup/
├── 01_fundamentals/
├── 02_control_flow/
├── ...
```

---

## Key rules

### 1. Separate logic from entry point

```python
# main.py
from src.app import run

run()
```

---

### 2. Keep reusable code in modules

```python
# src/utils.py
def add(a, b):
    return a + b
```

---

### 3. Avoid large files

* One concept per file
* Keep files focused

---

## Notes

* Structure becomes more important as projects grow
* Clean structure = easier debugging + scaling

