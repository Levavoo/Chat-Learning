# Logistic Regression

## What it is
Logistic regression is a supervised learning algorithm used for **classification**, not regression.

It predicts the **probability** that an input belongs to a class (usually 0 or 1).

---

## Why it matters
It is one of the most important classification algorithms.

Used for:
- binary classification problems
- baseline models
- understanding probabilities in ML

---

## Mathematical idea

Instead of predicting a line, logistic regression uses the **sigmoid function**:

p = 1 / (1 + e^-(w * x + b))

This converts any number into a value between 0 and 1.

---

## Key concept: Probability

The model outputs:

p = P(y = 1 | x)

Then we classify:

- if p ≥ 0.5 → class 1
- if p < 0.5 → class 0

---

## Loss function

Logistic regression uses **Binary Cross-Entropy (Log Loss)**:

Loss = -[y * log(p) + (1 - y) * log(1 - p)]

Why:
- penalizes wrong confident predictions heavily
- works well with probabilities

---

## Example intuition

Input:
- X = hours studied

Output:
- y = pass (1) or fail (0)

Instead of predicting a score, we predict:

- probability of passing

Example:
- 2 hours → 0.2 (likely fail)
- 5 hours → 0.7 (likely pass)

---

## Files in this folder

- example_plain_python.py  
  Manual implementation (with gradient descent)

- example_sklearn.py  
  Practical implementation using sklearn

---

## What to look for in the code

- sigmoid function
- how probabilities are computed
- how weights are updated (gradient descent)
- how classification threshold works

---

## Expected output

- learned parameters (w, b)
- predicted probabilities
- predicted classes (0 or 1)

---

## When to use it

Use when:
- output is categorical (especially binary)

Examples:
- spam detection
- disease prediction
- fraud detection
- pass/fail prediction

---

## Common mistakes

- thinking it predicts continuous values like linear regression
- forgetting it outputs probabilities
- not applying threshold (0.5)
- misunderstanding sigmoid behavior