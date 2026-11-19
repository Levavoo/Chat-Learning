from sklearn.model_selection import cross_val_score
from sklearn.linear_model import LinearRegression
import numpy as np

X = np.array([[1],[2],[3],[4]])
y = np.array([2,4,6,8])

model = LinearRegression()

scores = cross_val_score(model, X, y, cv=2)

print(scores)