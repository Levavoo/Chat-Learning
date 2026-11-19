---
type: learnpaper
kind: concept
technology: Python
chapter: 07_oop
level: intermediate
status: draft
tags: [python, oop]
---

# Instance Vs Class Attributes

> **Core idea:** Distinguish per-object and shared class data.

## Learning objectives

- Explain why the technique exists and identify where it is useful.
- Predict and verify the companion program's behavior.
- Recognize the main pitfall and solve a variation independently.

## Concept and motivation

**Instance Vs Class Attributes** is part of the broader topic **Oop**. Distinguish per-object and shared class data. Think of it as a tool for expressing a particular operation clearly rather than syntax to memorize. When reading an implementation, ask: *What information goes in? What operation happens? What result or side effect comes out?*

## Mental model

```mermaid
flowchart LR
    A["Input / initial state"] --> B["Instance Vs Class Attributes"]
    B --> C["Result / changed state"]
```

Find all three stages in the companion example. For I/O and mutable data, the effect can be external or in-place rather than a new returned value. For ML examples, also identify training and evaluation data separately.

## Practical walkthrough

**Companion example:** [02_instance_vs_class_attributes.py](02_instance_vs_class_attributes.py) (Python script).

1. **Read:** Locate the input variables, imports and main operation; paraphrase their purpose.
2. **Predict:** Before running, write down the expected result and which expressions cause it.
3. **Execute:** Run the script in VS Code using `python 02_instance_vs_class_attributes.py` from this chapter folder.
4. **Modify:** Change exactly one parameter or input and explain any difference.
5. **Extend:** Implement the challenge below in a separate scratch file; keep the reference script intact.

**What to notice:** Distinguish per-object and shared class data. The important part is being able to explain the mechanism rather than remembering output for one fixed input.

## Common mistakes and edge cases

**Pitfall:** Mutable class attributes may be accidentally shared.

Try an empty input, unexpected type, boundary value or error condition where appropriate. If the sample does not contain that case, implement it in your practice copy. Do not assume one successful example proves a general rule.

## Practice task

**Your task:** Compare two instance counters.

Afterward answer: What did you expect? What happened? What would fail, and how would you test that possibility?

## Self-check

- [ ] I can describe the concept without looking at this page.
- [ ] I ran the linked example and predicted its result.
- [ ] I modified the example, checked an edge case and solved the task.
- [ ] I can connect this topic to a realistic Python application.

## Connections and sources

- [Chapter index](README.md)
- Previous: [[01_classes_objects]]
- Next: [[03_inheritance]]
- [Python official documentation](https://docs.python.org/3/)
