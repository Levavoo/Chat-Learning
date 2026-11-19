# Advanced Python

## Goal
Understand deeper Python mechanics, performance, and system-level behavior.

---

## Topics
- closures
- descriptors
- abstract base classes (ABC) & protocols
- __slots__
- threading
- multiprocessing
- asyncio
- memory model

---

## What you should know after this section

- understand how Python functions retain state (closures)
- control attribute access (descriptors)
- design proper interfaces (ABC / Protocols)
- optimize memory usage
- understand concurrency vs parallelism
- write async code
- understand Python memory behavior

---

## Key concepts

### Closure
Function remembers variables from outer scope

### Descriptor
Custom logic for attribute access

### Threading vs Multiprocessing
- threading → shared memory (GIL)
- multiprocessing → separate processes

### Async
- cooperative multitasking (event loop)

---

## Common mistakes

- misunderstanding GIL (threads ≠ true parallel CPU work)
- overusing async unnecessarily
- writing unreadable async code
- ignoring memory costs in large data tasks