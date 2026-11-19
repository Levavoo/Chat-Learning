# Linear Regression

## What it is
Linear regression is a supervised learning algorithm used to predict a continuous value based on one or more input features.

It assumes a linear relationship between input (X) and output (y):

y = w * x + b

- w: slope (weight)
- b: intercept (bias)

---

## Why it matters
It is one of the simplest and most important ML models.

It is used as:
- a baseline model
- a foundation for more complex algorithms
- a way to understand optimization and loss functions

---

## Mathematical idea

The model tries to find the best line that minimizes error.

The most common loss function is Mean Squared Error (MSE):

MSE = (1/n) * Σ(y_true - y_pred)^2

Goal:
Find w and b that minimize MSE.

---

## Example intuition

If:
- X = hours studied
- y = exam score

Linear regression finds a rule like:

score = 5.5 * hours + 46.8

So:
- more study → higher score
- prediction works for unseen values

---

## Files in this folder

- example_plain_python.py  
  Manual implementation (no ML libraries)

- example_sklearn.py  
  Practical implementation using sklearn

---

## What to look for in the code

- How w (slope) is calculated
- How b (intercept) is calculated
- How predictions are made
- How error (MSE) is computed

---

## Expected output

- Learned slope and intercept
- Predictions for training data
- Prediction for a new value
- Error value (MSE)

---

## When to use it

Use when:
- target is continuous (number)
- relationship is roughly linear

Examples:
- price prediction
- score prediction
- demand forecasting

---

## Common mistakes

- Using it for classification problems
- Assuming all relationships are linear
- Ignoring outliers
- Not evaluating error (MSE)