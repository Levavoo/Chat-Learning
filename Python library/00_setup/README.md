---
type: chapter-index
kind: tool
technology: Python
chapter: 00_setup
status: learning
tags: [python, setup, navigation]
---

# Chapter 00 — Python Environment and Setup

Before studying Python syntax, learn how to install Python, run a script, manage packages and isolate project dependencies.

## Learning order

1. [Python installation](python_installation.md)
2. [Project structure](project_structure.md)
3. [Virtual environments](virtualenv.md)
4. [pip basics](pip_basics.md)
5. [uv basics](uv_basics.md)
6. [Jupyter basics](jupyter_basics.ipynb)

## Mental model

~~~mermaid
flowchart LR
    P["Python interpreter"] --> V["Project environment"]
    U["uv / pip"] --> V
    V --> S["Script or notebook"]
~~~

## Practice

Create a scratch project, run a Python script, install a harmless dependency, and identify which interpreter ran it.

## Self-check

- [ ] I can distinguish the interpreter, environment, and package manager.
- [ ] I can explain why virtual environments are ignored by Git.
- [ ] I can run a Python script and notebook.

## Navigation

- [Python library home](../README.md)
- [[Home]]
