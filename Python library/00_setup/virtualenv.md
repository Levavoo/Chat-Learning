# Virtual Environments

## Goal

Isolate project dependencies.

---

## 1. Create environment

```bash
python -m venv .venv
```

---

## 2. Activate environment

### Windows

```bash
.venv\Scripts\activate
```

### macOS / Linux

```bash
source .venv/bin/activate
```

---

## 3. Verify activation

```bash
which python
```

Should point to `.venv`

---

## 4. Install packages

```bash
pip install numpy pandas
```

---

## 5. Save dependencies

```bash
pip freeze > requirements.txt
```

---

## 6. Deactivate

```bash
deactivate
```

---

## Notes

* Always create a venv per project
* Never install packages globally
* Keep `.venv/` in `.gitignore`
