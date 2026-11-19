# Python Installation

## Goal

Install Python correctly and verify that your environment works.

---

## 1. Check if Python is already installed

Open terminal:

```bash
python --version
```

or

```bash
python3 --version
```

Expected output:

```
Python 3.11.x
```

---

## 2. Install Python (if not installed)

### Windows

* Download from: https://www.python.org
* IMPORTANT: Check **"Add Python to PATH"**
* Install

### macOS (recommended via Homebrew)

```bash
brew install python
```

### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip
```

---

## 3. Verify installation

```bash
python --version
pip --version
```

---

## 4. Run Python

```bash
python
```

Exit:

```python
exit()
```

---

## 5. Run a script

Create `test.py`:

```python
print("Python works")
```

Run:

```bash
python test.py
```

---

## Notes

* Use Python **3.10+**
* Avoid mixing `python` and `python3` inconsistently
* Always verify PATH issues first if something fails
