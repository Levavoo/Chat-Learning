# Gradient Boosting (XGBoost / LightGBM)

## Why important
- very strong performance on tabular data
- widely used in industry and competitions

---

## Concepts
- boosting = sequential learning
- correct previous errors
- combine weak learners into strong model

---

## Libraries
- xgboost
- lightgbm
- catboost

---

## When to use
- structured/tabular data
- medium-size datasets

---

## Basic usage (XGBoost)

```python
from xgboost import XGBClassifier

model = XGBClassifier()
model.fit(X, y)


---

## `14_advanced_ml_path/06_intro_to_neural_networks.ipynb`

```python
from sklearn.neural_network import MLPClassifier

X = [[0,0],[0,1],[1,0],[1,1]]
y = [0,1,1,0]

model = MLPClassifier(hidden_layer_sizes=(4,), max_iter=1000)
model.fit(X, y)

print(model.predict([[1,0]]))