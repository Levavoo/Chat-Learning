# pip Basics

## Goal

Manage Python packages.

---

## Install package

```bash
pip install requests
```

---

## Install specific version

```bash
pip install requests==2.31.0
```

---

## Upgrade package

```bash
pip install --upgrade requests
```

---

## Uninstall

```bash
pip uninstall requests
```

---

## List installed packages

```bash
pip list
```

---

## Freeze dependencies

```bash
pip freeze > requirements.txt
```

---

## Install from file

```bash
pip install -r requirements.txt
```

---

## Notes

* Always use pip inside a virtual environment
* Keep dependencies minimal
* Avoid installing unused packages
