# Error Handling

## Goal
Write code that handles errors gracefully instead of crashing.

---

## Topics
- try / except
- catching specific exceptions
- else / finally
- raising exceptions
- custom exceptions

---

## What you should know after this section

- prevent program crashes
- handle user input safely
- debug errors effectively
- raise meaningful errors
- understand common exception types

---

## Common exception types

- ValueError → wrong value type
- TypeError → wrong data type usage
- KeyError → missing dictionary key
- IndexError → invalid list index
- ZeroDivisionError → division by zero
- FileNotFoundError → missing file

---

## Key concepts

### try / except
- try → code that might fail
- except → what to do if it fails

### else
- runs if no error occurred

### finally
- always runs (cleanup)

### raise
- manually trigger an error

---

## Common mistakes

- catching all exceptions blindly (`except:`)
- hiding real errors
- not understanding why the error happened
- overusing try/except instead of fixing logic

---

## Suggested order

1. 01_try_except.py
2. 02_specific_exceptions.py
3. 03_else_finally.py
4. 04_raise.py
5. 05_custom_exceptions.py